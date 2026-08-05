"""The REST API and the static host for the dashboard. (CLAUDE.md)

Runs on the user's machine by default, not on the internet. That is a deliberate scoping
decision, not an oversight: the honest way to store an API key with no accounts is to not
be reachable from the network in the first place, so the server binds to localhost.

A deployment that *is* reachable sets `FIREBASE_PROJECT_ID` and `ALLOWED_EMAILS`, and
then every route below requires a signed-in, allow-listed person — see `app/auth.py` and
docs/DEPLOY-ORACLE.md §8. There is no third state. Either nothing can reach the app, or
the app checks who is asking.

Everything the browser can do:

    GET    /api/state                  everything the dashboard needs, in one call
    GET    /api/settings               PUT to change the weekly knobs
    POST   /api/settings/api-key       store a key   DELETE to remove it
    POST   /api/settings/api-key/test  check a key works, without storing it
    GET    /api/programs               POST to add
    PUT    /api/programs/{id}          DELETE to remove
    POST   /api/programs/draft         the card assistant — drafts, never saves
    GET    /api/funders                POST to add
    PUT    /api/funders/{id}           DELETE to remove
    GET    /api/opportunities          this month's findings, in their reading order
    GET    /api/opportunities/export.csv  ← the "Download as a spreadsheet" button
    GET    /api/archive                the archive, by month
    GET    /api/runs                   run history
    POST   /api/runs                   ← the "Re-run search pipeline" button
    POST   /api/runs/stop              ← the stop button
    GET    /api/runs/current           live progress while one is going

    GET    /api/health                 public — an uptime ping, holds nothing
    GET    /api/auth/config            public — is sign-in on, and the Firebase project
    GET    /api/auth/me                who the server thinks you are

There is no endpoint that returns the Anthropic API key. That is not an omission.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import archive, auth, export, repo, scheduler, secrets
from .db import (DEFAULT_ORG_ID, SECTORS, InviteError, create_invite, import_starter_list,
                 init_db, list_invites, month_key, org_for_user, org_members,
                 redeem_invite, revoke_invite, session)
from .runner import MANAGER

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dashboard" / "dist"

# Two routers, and the split is the security boundary. Everything on `api` is behind
# `auth.require_user`; `public` holds only the two things that must answer before anyone
# can possibly be signed in, and neither of them reveals anything.
api = APIRouter(prefix="/api")
public = APIRouter(prefix="/api")


# --- whose data is this? ------------------------------------------------------

def current_org(user=Depends(auth.require_user)) -> str:
    """The org whose data this request may touch. Every `/api` handler takes it.

    This is the tenant boundary, and it is deliberately the *only* way a handler learns
    an org id — none of them accept one from the client. An org id in a query parameter
    or a request body would be an invitation to type somebody else's.

    With sign-in off there is no user to ask, and a local install binds to 127.0.0.1 with
    exactly one org, so it resolves to `DEFAULT_ORG_ID`. That keeps `./start.sh` a
    zero-configuration experience without giving a deployed install a way to reach the
    default org's data: on a deployed box `auth.require_user` has already raised 401
    before this function runs.
    """
    if user is None:
        return DEFAULT_ORG_ID
    with session() as conn:
        return org_for_user(conn, user.uid, user.email)


# --- request bodies -----------------------------------------------------------

class SettingsIn(BaseModel):
    min_award: int | None = Field(None, ge=0)
    min_deadline_runway_days: int | None = Field(None, ge=0, le=365)
    max_opportunities: int | None = Field(None, ge=1, le=100)
    run_budget_usd: float | None = Field(None, gt=0, le=20)
    enabled: bool | None = None
    sectors_active: list[str] | None = None
    search_beyond_partners: bool | None = None
    org_name: str | None = Field(None, max_length=200)
    org_location: str | None = Field(None, max_length=200)
    # The weekly schedule. Validated here rather than trusted: `schedule_hour` reaches a
    # `.replace(hour=...)` in the scheduler, and the timezone reaches ZoneInfo — which
    # handles a bad name gracefully, but there is no reason to make it.
    schedule_day: str | None = Field(None, pattern="^(monday|tuesday|wednesday|thursday|"
                                                   "friday|saturday|sunday)$")
    schedule_hour: int | None = Field(None, ge=0, le=23)
    schedule_timezone: str | None = Field(None, max_length=64)


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


class ApiKeyTestIn(BaseModel):
    """Testing an unsaved key and testing the saved one are the same request with and
    without a body, so the field has to be genuinely optional — `ApiKeyIn | None` is
    not, because an empty `{}` still gets validated against the required field."""

    api_key: str | None = None


class ProgramIn(BaseModel):
    name: str | None = None
    summary: str | None = None
    what_it_funds: str | None = None
    keywords: list[str] | None = None
    funder_types: list[str] | None = None
    search_queries: list[str] | None = None
    min_award: int | None = None
    active: bool | None = None
    source_url: str | None = None
    drafted_by_ai: bool | None = None
    reviewed_by_human: bool | None = None


class FunderIn(BaseModel):
    name: str | None = None
    url: str | None = None
    sector: str | None = None
    funder_type: str | None = None
    warm: bool | None = None
    active: bool | None = None
    tier: int | None = Field(None, ge=0, le=3)
    programs: list[str] | None = None
    notes: str | None = None
    exclude_reason: str | None = None


class DraftIn(BaseModel):
    url: str


class RunIn(BaseModel):
    no_llm: bool = False
    budget: float | None = Field(None, gt=0, le=20)
    max_opportunities: int | None = Field(None, ge=1, le=100)


def _set(model: BaseModel) -> dict[str, Any]:
    """Only the fields the client actually sent. A PUT that omits a field must leave it
    alone rather than reset it to a default — otherwise editing one thing on a card
    silently wipes the rest."""
    return model.model_dump(exclude_unset=True, exclude_none=True)


# --- settings -----------------------------------------------------------------

def _key_state(conn, org_id: str) -> dict:
    """What the browser is allowed to know about the API key.

    Three facts, no secret: is one saved *here*, is one reaching the pipeline at all,
    and which of the two is actually in play. That last one matters because a `.env`
    on the machine makes the pipeline score whether or not Settings holds anything —
    without saying so, the page would imply a key is saved when it is not.
    """
    stored = secrets.read_api_key(conn, org_id=org_id)
    effective, source = secrets.resolve_api_key(conn, org_id=org_id)
    return {
        # A hint, never the key. There is no path that returns the secret.
        "api_key_hint": secrets.mask(stored),
        "has_api_key": bool(stored),          # saved in Settings
        "key_available": bool(effective),     # the pipeline can score
        "api_key_source": source,             # "settings" | "environment" | None
        "env_key_hint": secrets.mask(effective) if source == "environment" else None,
    }


@api.get("/settings")
def read_settings(org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {
            "settings": repo.get_settings(conn, org_id=org),
            "sectors_available": list(SECTORS),
            **_key_state(conn, org),
        }


@api.put("/settings")
def write_settings(body: SettingsIn, org: str = Depends(current_org)) -> dict:
    changes = _set(body)
    if "sectors_active" in changes:
        unknown = [s for s in changes["sectors_active"] if s not in SECTORS]
        if unknown:
            raise HTTPException(400, f"Unknown sector(s): {', '.join(unknown)}")
    with session() as conn:
        return {"settings": repo.update_settings(conn, changes, org_id=org)}


@api.post("/settings/api-key")
def save_api_key(body: ApiKeyIn, org: str = Depends(current_org),
                 user=Depends(auth.require_user)) -> dict:
    key = body.api_key.strip()
    with session() as conn:
        secrets.store_api_key(conn, key, org_id=org)
        # Name the actor. Replacing the key changes who pays for every subsequent run,
        # and a log line reading only "API key saved" is unattributable the moment more
        # than one person can sign in.
        log.info("API key saved for org %s by %s (%s)",
                 org, user.email if user else "local", secrets.mask(key))
        return _key_state(conn, org)


@api.delete("/settings/api-key")
def delete_api_key(org: str = Depends(current_org),
                   user=Depends(auth.require_user)) -> dict:
    with session() as conn:
        secrets.clear_api_key(conn, org_id=org)
        log.info("API key removed for org %s by %s",
                 org, user.email if user else "local")
        # Reports honestly if an environment key is still in play — otherwise deleting
        # here looks like it stopped the agent scoring when it did not.
        return _key_state(conn, org)


@api.post("/settings/api-key/test")
def test_api_key(body: ApiKeyTestIn | None = None,
                 org: str = Depends(current_org)) -> dict:
    """Check a key works before trusting it. One token, so effectively free.

    Accepts a key in the body to test before saving, or falls back to the saved one —
    so "is the key I already have still good?" is answerable without re-typing it.
    """
    key = (body.api_key.strip() if body and body.api_key else None)
    if not key:
        with session() as conn:
            key = secrets.read_api_key(conn, org_id=org)
    if not key:
        return {"ok": False, "message": "No API key saved yet."}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5", max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"ok": True, "message": "That key works."}
    except Exception as exc:  # noqa: BLE001
        # Report the failure, never the key, and never a raw stack to the browser.
        name = type(exc).__name__
        if "Authentication" in name:
            return {"ok": False, "message": "That key was rejected by Anthropic."}
        return {"ok": False, "message": f"Could not reach Anthropic ({name})."}


# --- programs -----------------------------------------------------------------

@api.get("/programs")
def list_programs(org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {"programs": repo.list_programs(conn, org_id=org)}


@api.post("/programs", status_code=201)
def create_program(body: ProgramIn, org: str = Depends(current_org)) -> dict:
    try:
        with session() as conn:
            return {"program": repo.create_program(conn, _set(body), org_id=org)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.put("/programs/{program_id}")
def update_program(program_id: str, body: ProgramIn,
                   org: str = Depends(current_org)) -> dict:
    with session() as conn:
        updated = repo.update_program(conn, program_id, _set(body), org_id=org)
    if updated is None:
        raise HTTPException(404, "No such program.")
    return {"program": updated}


@api.delete("/programs/{program_id}")
def delete_program(program_id: str, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        if not repo.delete_program(conn, program_id, org_id=org):
            raise HTTPException(404, "No such program.")
    return {"deleted": program_id}


@api.post("/programs/draft")
async def draft_program(body: DraftIn, org: str = Depends(current_org)) -> dict:
    """The assistant. Returns a draft for the user to review — saves nothing."""
    from .assistant import AssistantError, draft_program_card

    with session() as conn:
        key = secrets.effective_api_key(conn, org_id=org)
    try:
        return {"draft": await draft_program_card(body.url.strip(), key)}
    except AssistantError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("assistant failed")
        raise HTTPException(500, f"The assistant could not finish ({type(exc).__name__}).") from exc


# --- funders ------------------------------------------------------------------

@api.get("/funders")
def list_funders(org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {"funders": repo.list_funders(conn, org_id=org),
                "sectors_available": list(SECTORS)}


@api.post("/funders", status_code=201)
def create_funder(body: FunderIn, org: str = Depends(current_org)) -> dict:
    try:
        with session() as conn:
            return {"funder": repo.create_funder(conn, _set(body), org_id=org)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.put("/funders/{funder_id}")
def update_funder(funder_id: str, body: FunderIn,
                  org: str = Depends(current_org)) -> dict:
    with session() as conn:
        updated = repo.update_funder(conn, funder_id, _set(body), org_id=org)
    if updated is None:
        raise HTTPException(404, "No such funder.")
    return {"funder": updated}


@api.delete("/funders/{funder_id}")
def delete_funder(funder_id: str, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        if not repo.delete_funder(conn, funder_id, org_id=org):
            raise HTTPException(404, "No such funder.")
    return {"deleted": funder_id}


# --- how the whole install is doing -------------------------------------------

def require_admin(user=Depends(auth.require_user)) -> None:
    """The one route that reads across every organization, gated separately.

    `FUNDWORTHY_ADMIN_EMAILS` is its own list, not a role on the user, and not
    `ALLOWED_EMAILS`: with open sign-up that one is empty, so hanging admin off "are you
    signed in" would publish the platform's numbers to anybody who made an account. Unset
    means **nobody** — a missing variable must not be a permissive default on the only
    endpoint that ignores the tenant boundary.

    A local install (no sign-in) is one person on 127.0.0.1 looking at their own box, so
    it is allowed.
    """
    import os

    if not auth.enabled():
        return
    admins = {e.strip().casefold()
              for e in os.environ.get("FUNDWORTHY_ADMIN_EMAILS", "").split(",")
              if e.strip()}
    if not admins or user is None or user.email.casefold() not in admins:
        # 404, not 403: an endpoint that says "you are not an admin" has confirmed it
        # exists and that being an admin is a thing to become.
        raise HTTPException(404, "Not found.")


@api.get("/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats() -> dict:
    """Counts and money, across the install. No names, no findings, no funder lists."""
    with session() as conn:
        return repo.platform_stats(conn)


# --- the starter directory ----------------------------------------------------

@api.get("/directory")
def read_directory(org: str = Depends(current_org)) -> dict:
    """Funder lists an org can import, and how many of each it already has.

    These used to be seeded into whichever org signed in first, which meant one account
    had 52 funders and the one created after it had none. They are a directory now:
    everybody sees the same thing and chooses. See FUTURE.md §4a for where this goes.
    """
    from agent.directory import STARTER_LISTS, catalogue
    from app.db import _funder_id

    with session() as conn:
        mine = {r["id"] for r in
                conn.execute("SELECT id FROM funders WHERE org_id=?", (org,))}

    have = {lst.key: sum(1 for s in lst.sources
                         if _funder_id(s.funder, s.url) in mine)
            for lst in STARTER_LISTS}
    return {"lists": [{**entry, "imported": have.get(entry["key"], 0)}
                      for entry in catalogue()]}


@api.post("/directory/{key}/import")
def import_directory_list(key: str, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        try:
            added = import_starter_list(conn, key, org)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"added": added, "funders": repo.list_funders(conn, org_id=org)}


# --- findings -----------------------------------------------------------------

@api.get("/opportunities")
def list_opportunities(month: str | None = None, run_id: str | None = None,
                       org: str = Depends(current_org)) -> dict:
    with session() as conn:
        rows = repo.list_opportunities(conn, org_id=org,
                                       month=month or month_key(), run_id=run_id)
    return {
        "month": month or month_key(),
        "opportunities": rows,
        # Split out so the UI never has to re-derive the user's reading order. They asked
        # for the clean results first and the ambiguous ones at the bottom.
        "clear": [r for r in rows if not r["needs_human_check"]],
        "needs_check": [r for r in rows if r["needs_human_check"]],
    }


@api.get("/opportunities/export.csv")
def export_opportunities(month: str | None = None, run_id: str | None = None,
                         org: str = Depends(current_org)):
    """Download the brief as a spreadsheet file. (CLAUDE.md)

    Deliberately not the Phase 3 OAuth push into their live Sheet: this needs no Google
    credential, so there is nothing here that can expire, get revoked, or need a
    consent screen re-verified before a demo. They open the file in Sheets.

    Same rows and same order as GET /opportunities — one query, one sort, so the file
    can never disagree with the page they downloaded it from.
    """
    key = month or month_key()
    with session() as conn:
        rows = repo.list_opportunities(conn, org_id=org, month=key, run_id=run_id)
    return Response(
        content=export.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        # Without this the browser renders the CSV as text instead of saving it.
        headers={"Content-Disposition": f'attachment; filename="{export.filename(key)}"'},
    )


@api.get("/archive")
def read_archive(month: str | None = None, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        summary = archive.month_summary(conn, org_id=org)
        rows = repo.list_opportunities(conn, org_id=org, month=month) if month else []
        months = repo.available_months(conn, org_id=org)
    return {**summary, "months_available": months,
            "month": month, "opportunities": rows}


# --- runs ---------------------------------------------------------------------

@api.get("/runs")
def list_runs(limit: int = 20, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {"runs": repo.list_runs(conn, limit=limit, org_id=org)}


@api.get("/runs/current")
def current_run(org: str = Depends(current_org)) -> dict:
    """This org's current run — or its last one if nothing is going.

    Scoped to the org throughout: "is a run happening" and "is *your* run happening" are
    different questions, and answering the first showed every org a spinner, a live log
    of another nonprofit's funders, and a Stop button for a run that was not theirs.
    """
    mine = MANAGER.current_run_id_for(org)
    with session() as conn:
        run = repo.get_run(conn, mine, org_id=org) if mine \
            else repo.latest_run(conn, org_id=org)
    return {"running": bool(mine), "run": run, "log": MANAGER.log_tail(org)}


@api.post("/runs", status_code=202)
def start_run(body: RunIn, org: str = Depends(current_org),
              user=Depends(auth.require_user)) -> dict:
    """The "Re-run search pipeline" button."""
    with session() as conn:
        if not repo.get_settings(conn, org_id=org)["enabled"]:
            raise HTTPException(
                409, "The agent is switched off. Turn it back on in Settings first.")
    try:
        run_id = MANAGER.start(no_llm=body.no_llm, budget=body.budget,
                               max_opportunities=body.max_opportunities,
                               org_id=org, started_by=user.email if user else None)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "running": True}


@api.post("/runs/stop")
def stop_run(org: str = Depends(current_org)) -> dict:
    """Stop **your** run.

    Previously this stopped whatever the singleton was holding, with no check on who was
    asking — so one org's staffer, seeing a spinner and a log full of funders they did not
    recognise, could SIGTERM another nonprofit's five-minute run and destroy the money
    already spent on it.
    """
    return {"stopped": MANAGER.stop(org_id=org)}


# --- one call for the whole dashboard -----------------------------------------

@api.get("/state")
def state(org: str = Depends(current_org)) -> dict:
    """Everything the main page needs. One request instead of six, so the dashboard
    cannot render itself half-populated while the rest arrives."""
    with session() as conn:
        rows = repo.list_opportunities(conn, org_id=org, month=month_key())
        return {
            "settings": repo.get_settings(conn, org_id=org),
            **_key_state(conn, org),
            "sectors_available": list(SECTORS),
            "programs": repo.list_programs(conn, org_id=org),
            "funders": repo.list_funders(conn, org_id=org),
            "month": month_key(),
            "clear": [r for r in rows if not r["needs_human_check"]],
            "needs_check": [r for r in rows if r["needs_human_check"]],
            "latest_run": repo.latest_run(conn, org_id=org),
            "running": bool(MANAGER.current_run_id_for(org)),
            "spend": repo.spend_summary(conn, org_id=org),
        }


# --- the two public routes ----------------------------------------------------

@public.get("/health")
def health() -> dict:
    """Deliberately outside the sign-in gate, and deliberately empty.

    It has to be reachable without credentials to be useful — it is what nginx, a
    monitor, or the periodic ping that stops Oracle reclaiming an idle free VM
    (FUTURE.md §1) would call. So it must never grow a field. The moment it reports a
    run count or an org name it is an unauthenticated data endpoint.
    """
    return {"ok": True}


@public.get("/maintenance")
def maintenance() -> dict:
    """Is an update happening right now.

    Public, and deliberately so: the whole point is that somebody who is *not* signed in
    still learns why the page is about to blink. It says one boolean and a sentence the
    deploy wrote — never a count, never a name, never anything about who is using the app.
    """
    from .runner import drain_notice, draining

    active = draining()
    return {
        "maintenance": active,
        "message": (drain_notice() if active else "") or (
            "Fundworthy is being updated. Searches already running will finish; new "
            "ones can start again in a few minutes." if active else ""),
    }


@public.get("/auth/config")
def auth_config() -> dict:
    """Is sign-in on, and which Firebase project. Public because the sign-in page needs
    it before anyone can be signed in. See `auth.browser_config` for why none of it is
    secret."""
    return auth.browser_config()


# --- your organization --------------------------------------------------------

@api.get("/org")
def read_org(org: str = Depends(current_org)) -> dict:
    """Who is in your org, and the outstanding invitations."""
    with session() as conn:
        row = conn.execute("SELECT name FROM orgs WHERE id=?", (org,)).fetchone()
        return {
            "org_id": org,
            "name": (row["name"] if row else "") or "",
            "members": org_members(conn, org),
            "invites": [i for i in list_invites(conn, org) if not i["redeemed_at"]],
        }


@api.post("/org/invites", status_code=201)
def make_invite(org: str = Depends(current_org),
                user=Depends(auth.require_user)) -> dict:
    """Create a code that lets one colleague join this org.

    Anyone in the org can invite, because there are no roles yet — everyone who can
    already replace the API key can also add a colleague, so a role check here would be
    theatre. Roles are FUTURE.md §2.
    """
    with session() as conn:
        invite = create_invite(conn, org, created_by=user.email if user else None)
    log.info("invite created for org %s by %s", org, user.email if user else "local")
    return {"invite": invite}


@api.delete("/org/invites/{code}")
def drop_invite(code: str, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        if not revoke_invite(conn, code, org):
            raise HTTPException(404, "No such unused invitation.")
    return {"revoked": code}


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=64)


@api.post("/org/join")
def join_org(body: JoinIn, user=Depends(auth.require_user)) -> dict:
    """Redeem an invitation and move into that colleague's organization.

    Note this deliberately does **not** depend on `current_org`: resolving the caller's
    current org would create an empty one for them a moment before they leave it.
    """
    if user is None:
        raise HTTPException(
            400, "Joining an organization needs sign-in, which this install has off.")
    try:
        with session() as conn:
            org_id = redeem_invite(conn, body.code, user.uid, user.email)
    except InviteError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"org_id": org_id, "joined": True}


@api.get("/auth/me")
def whoami(user=Depends(auth.require_user), org: str = Depends(current_org)) -> dict:
    """Who the *server* thinks you are. The browser already has a Firebase user object,
    so this exists to check the two agree — a token the allow-list rejects should fail
    here rather than after the dashboard has half-rendered."""
    if user is None:
        return {"signed_in": False, "auth_required": False, "org_id": org}
    return {"signed_in": True, "auth_required": True,
            "email": user.email, "name": user.name, "org_id": org}


# --- app ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # A restart is the last step of every deploy, and it kills any pipeline subprocess
    # along with the API that launched it. Run state lives in `RunManager`, in this
    # process's memory, so nothing survives to write those rows back — they stay at
    # 'running' for ever and the dashboard shows a permanent spinner for a search that
    # died days ago. Reconcile before serving.
    with session() as conn:
        repo.reconcile_interrupted_runs(conn)

    # The weekly run, per org, on the day and hour they chose. In-process on purpose —
    # see app/scheduler.py for why a systemd timer would bypass the drain gate, the
    # concurrency cap, and per-org API keys.
    stop_scheduler = threading.Event()
    scheduler.start(stop_scheduler)

    log.info("Fundworthy ready.")
    yield
    stop_scheduler.set()


def create_app() -> FastAPI:
    # uvicorn configures its own three loggers and leaves the root logger with no
    # handler, so until this line every log call in this application went nowhere:
    # "Fundworthy ready.", which mode sign-in came up in, and — the one that matters —
    # who was refused and why. On a VM `journalctl -u fundworthy` showed four uvicorn
    # lines and nothing else, which is not enough to debug a locked-out user.
    #
    # basicConfig is a no-op when the root logger already has handlers, so a caller with
    # its own logging setup keeps it. journald stamps the time and the unit, so the
    # format only has to say which logger spoke.
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")

    # Before anything is mounted, because a bad sign-in configuration is a refusal to
    # start, never a fallback to open. Same doctrine as FUNDWORTHY_STRICT_CONFIG.
    auth.configure()

    app = FastAPI(
        title="Fundworthy",
        description="Control surface for a nonprofit's funding-opportunity agent.",
        version="2.0.0",
        # The interactive docs enumerate every route and body shape. Harmless on a
        # localhost install, an unnecessary map of the building on a public one.
        docs_url=None if auth.enabled() else "/api/docs",
        redoc_url=None,
        openapi_url=None if auth.enabled() else "/openapi.json",
        lifespan=lifespan,
    )

    # The Vite dev server runs on another port during development. Localhost only —
    # this is not an invitation for anything else to call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        # The CSV download reads its filename off this header. Same-origin in
        # production, cross-origin against the dev server, where it is invisible to JS
        # unless it is named here.
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        """Headers that tell the browser to be strict. Cheap, and they only start
        mattering once the app is reachable from somewhere other than localhost.

        No HSTS here on purpose: it belongs on the TLS terminator (nginx), and setting
        it from the app would also send it to a local `http://127.0.0.1:8000` install,
        pinning that hostname to HTTPS in the developer's browser for a year.
        """
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # The dashboard is self-hosted except for Google Fonts and Firebase Auth, both
        # of which the sign-in page loads dynamically. `connect-src` has to allow
        # Google's identity endpoints or sign-in breaks.
        response.headers.setdefault("Content-Security-Policy", "; ".join([
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://apis.google.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https:",
            "connect-src 'self' https://identitytoolkit.googleapis.com "
            "https://securetoken.googleapis.com https://www.googleapis.com",
            "frame-src https://accounts.google.com "
            "https://*.firebaseapp.com",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]))
        return response

    app.include_router(public)
    # One dependency, one router, every route. Not per-endpoint: a gate you have to
    # remember to add to each new route is a gate that gets forgotten on the one that
    # starts a run.
    app.include_router(api, dependencies=[Depends(auth.require_user)])

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            """Serve the built dashboard, falling back to index.html for client routes.

            **Except under `/api`.** This catch-all is registered last, so a request to an
            API route that does not exist — a typo, a removed endpoint, a client running
            against a newer server — used to fall through here and get `200` with a page
            of HTML. Every failure mode of that is quiet: a caller cannot tell "gone" from
            "fine", `curl` reports success, and anyone debugging reads the dashboard's
            markup wondering why their endpoint returns a favicon link.

            It is also how a stale deployment hides. `GET /api/maintenance` answering 200
            on a box that has never heard of that endpoint says the feature is live when
            the code is not on the machine at all.
            """
            if path.startswith("api/"):
                raise HTTPException(404, "No such endpoint.")
            candidate = (DIST / path).resolve()
            if path and candidate.is_file() and DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def not_built():
            return JSONResponse(
                {"error": "The dashboard has not been built yet.",
                 "fix": "Run ./start.sh, or `cd dashboard && npm install && npm run build`."},
                status_code=503,
            )

    return app


app = create_app()
