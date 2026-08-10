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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.models import MAX_REJECTS
from agent.score import (EFFORT_CHOICES, EFFORT_IDS, MODEL_CHOICES, PRICING,
                         SCORING_MODEL, TRIAGE_MODEL)
from . import archive, auth, export, repo, scheduler, secrets
from .db import (DEFAULT_ORG_ID, SECTORS, InviteError, create_invite, current_active_org,
                 import_starter_list, init_db, list_invites, month_key, my_orgs,
                 org_members, org_owner, redeem_invite, remove_member,
                 remove_starter_list, revoke_invite, session, set_org_owner,
                 switch_active_org)
from .runner import MANAGER, preflight

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
    or a request body would be an invitation to type somebody else's. `POST /api/org/
    switch` is the one legitimate exception, and it works precisely because it re-derives
    the same boundary rather than bypassing it: it takes an org id from the client too,
    but only ever *writes* it after checking a membership row exists — see
    `db.switch_active_org`.

    With sign-in off there is no user to ask, and a local install binds to 127.0.0.1 with
    exactly one org, so it resolves to `DEFAULT_ORG_ID`. That keeps `./start.sh` a
    zero-configuration experience without giving a deployed install a way to reach the
    default org's data: on a deployed box `auth.require_user` has already raised 401
    before this function runs.

    Resolves to the ACTIVE org, not always the home one — see `db.current_active_org`.
    Someone who has joined a second organization by invitation code and switched into it
    sees that org's data everywhere until they switch back.
    """
    if user is None:
        return DEFAULT_ORG_ID
    with session() as conn:
        return current_active_org(conn, user.uid, user.email)


# --- request bodies -----------------------------------------------------------

class SettingsIn(BaseModel):
    min_award: int | None = Field(None, ge=0)
    min_deadline_runway_days: int | None = Field(None, ge=0, le=365)
    max_opportunities: int | None = Field(None, ge=1, le=100)
    run_budget_usd: float | None = Field(None, gt=0, le=20)
    # The org's own ceiling on what Fundworthy may spend in a calendar month, across
    # every run — `run_budget_usd` bounds one run, this bounds the bill (app/db.py:
    # DEFAULT_SETTINGS). Without a declared field here, Pydantic silently dropped it
    # from every request before `_set()` ever saw it — the same shape of bug CLAUDE.md
    # documents for `blocked` on a funder: the Organization panel's "Change the monthly
    # limit" dialog showed a 200 back and closed as if it had saved, having changed
    # nothing. `le=500` matches the input's own long-standing `max`.
    monthly_budget_usd: float | None = Field(None, gt=0, le=500)
    enabled: bool | None = None
    # Set once, when somebody finishes the first-run walkthrough. Writable like any other
    # setting rather than through its own endpoint — it is a fact about the account, and
    # the settings table is where facts about the account live.
    onboarding_done: bool | None = None
    # Offer the funders this org typed in by hand to other nonprofits. Off by default;
    # turning it on schedules the reachability checks in `app/funder_check.py`.
    share_funders: bool | None = None
    sectors_active: list[str] | None = None
    search_beyond_partners: bool | None = None
    # `provider:model`, validated against PRICING below — an id with no price would
    # KeyError inside the run rather than here, which is the worst place to find out.
    triage_model: str | None = Field(None, max_length=80)
    scoring_model: str | None = Field(None, max_length=80)
    # The reasoning-depth dial for each tier, independent of the model above.
    # Validated against EFFORT_IDS below the same way the model ids are.
    triage_effort: str | None = Field(None, max_length=20)
    scoring_effort: str | None = Field(None, max_length=20)
    # Spend the whole budget instead of stopping at max_opportunities. See
    # agent/config.py: Config.ultra_mode.
    ultra_mode: bool | None = None
    org_name: str | None = Field(None, max_length=200)
    org_location: str | None = Field(None, max_length=200)
    # Hours this org can spend on one application. Decides 25 of the 100 scoring points
    # and used to be the constant `10` in the prompt — the pilot COO's answer, applied to
    # every tenant. Bounded here because a 0 makes everything infeasible and a 100,000
    # makes everything free.
    max_effort_hours: int | None = Field(None, ge=1, le=200)
    # The weekly schedule. Validated here rather than trusted: `schedule_hour` reaches a
    # `.replace(hour=...)` in the scheduler, and the timezone reaches ZoneInfo — which
    # handles a bad name gracefully, but there is no reason to make it.
    # The weekly automation, separate from `enabled`. `enabled` is the kill switch and
    # gates everything including the Search button; this only decides whether a search
    # also happens unattended. Conflating them meant switching off automation switched
    # off the manual button too.
    schedule_enabled: bool | None = None
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
    # Without this, Pydantic silently drops `blocked` from the request body before
    # `_set()` ever sees it — the Block button in the dashboard would save nothing.
    blocked: bool | None = None
    tier: int | None = Field(None, ge=0, le=3)
    region: str | None = None
    programs: list[str] | None = None
    notes: str | None = None
    exclude_reason: str | None = None


class DraftIn(BaseModel):
    url: str


class RunIn(BaseModel):
    no_llm: bool = False
    budget: float | None = Field(None, gt=0, le=20)
    max_opportunities: int | None = Field(None, ge=1, le=100)


def _schedule_funder_checks(org_id: str) -> None:
    """Check this org's unchecked hand-added funders, off the request thread.

    A daemon thread rather than an await: each check is an HTTP round trip to somebody
    else's website behind a politeness delay, so doing it inline would make ticking a
    checkbox take half a minute and adding one funder block on the network.

    Nothing depends on it finishing. An unchecked funder is simply not offered to anyone
    yet — `shared_funders` requires `check_ok = 1` — so a thread that dies takes nothing
    with it and the next trigger picks the work up again.
    """
    import asyncio

    from .funder_check import recheck_shared

    def run() -> None:
        try:
            asyncio.run(recheck_shared(session, org_id))
        except Exception:  # noqa: BLE001 — background work must not take the API down
            log.exception("funder checks failed for org %s", org_id)

    threading.Thread(target=run, daemon=True,
                     name=f"fundworthy-check-{org_id[:8]}").start()


def _same_page(a: str, b: str) -> bool:
    """Do these two links point at the same page, as a person would judge it.

    Case, a trailing slash and a leading `www.` are not differences anybody means, and
    treating them as differences would let the duplicate check be defeated by pasting the
    same link with one character changed. Query strings and fragments are kept: `?id=7`
    genuinely is a different programme.
    """
    def norm(u: str) -> str:
        u = u.strip().rstrip("/").casefold()
        for prefix in ("https://", "http://"):
            if u.startswith(prefix):
                u = u[len(prefix):]
        return u.removeprefix("www.")

    return bool(a) and bool(b) and norm(a) == norm(b)


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
    # A model with no price cannot be checked against the spend limit, and finding that
    # out is a KeyError on the first call of a run rather than an error here. Empty is
    # allowed and means "use whatever the code recommends".
    for field_name in ("triage_model", "scoring_model"):
        chosen = changes.get(field_name)
        if chosen and chosen not in PRICING:
            raise HTTPException(
                400, f"{chosen} is not a model Fundworthy knows the price of, so it "
                     "cannot be kept inside your spending limit.")
    # An effort id the API doesn't offer would reach the Anthropic call and 400 out
    # every triage or scoring request in the run — caught here instead, the same way
    # an unpriced model is.
    for field_name in ("triage_effort", "scoring_effort"):
        chosen = changes.get(field_name)
        if chosen and chosen not in EFFORT_IDS:
            raise HTTPException(
                400, f"{chosen!r} is not an effort level Fundworthy offers.")
    with session() as conn:
        settings = repo.update_settings(conn, changes, org_id=org)
    # Turning sharing on is what schedules the reachability checks. Nothing this org
    # added is offered to anybody until one has passed, so the tick is a request to be
    # checked rather than an instant publish.
    if changes.get("share_funders"):
        _schedule_funder_checks(org)
    return {"settings": settings}


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
    try:
        with session() as conn:
            updated = repo.update_program(conn, program_id, _set(body), org_id=org)
    except ValueError as exc:
        # Ticking a card with no description. The message is written for the person, not
        # for a log, because it is rendered straight into the panel.
        raise HTTPException(400, str(exc)) from exc
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

    url = body.url.strip()
    with session() as conn:
        # Refuse a page this org has already turned into a card. Reading it again would
        # cost a Sonnet call to produce a second copy of a programme they have, and the
        # duplicate then splits the search: two cards, both ticked, both querying for the
        # same work. Cheaper and clearer to say so before spending anything.
        #
        # Compared on the URL as stored, ignoring case, a trailing slash and a `www.`,
        # because those are the same page and nobody pasting a link thinks otherwise.
        existing = next(
            (p for p in repo.list_programs(conn, org_id=org)
             if p.get("source_url") and _same_page(p["source_url"], url)),
            None)
        if existing:
            raise HTTPException(
                409,
                f'You already have a program from that page — "{existing["name"]}". '
                "Edit that card instead, or paste a different page.")

        key = secrets.effective_api_key(conn, org_id=org)
    try:
        return {"draft": await draft_program_card(url, key)}
    except AssistantError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("assistant failed")
        raise HTTPException(500, f"The assistant could not finish ({type(exc).__name__}).") from exc


# --- funders ------------------------------------------------------------------

def _duplicate_funder(conn, org: str, name: str | None, url: str | None,
                      ignore_id: str | None = None) -> dict | None:
    """An existing funder that is really the same one, or None.

    Two ways to add a funder twice, and neither used to say anything:

      - **Same name.** `repo.create_funder` derives the id from the name and upserts, so
        a second "San Diego Foundation" silently overwrote the first — quietly editing a
        row the person thought they were creating, including its notes and its place on
        the remove list.
      - **Same page, different name.** Two rows pointing at one grants page, fetched
        twice every week, scored twice, and listed twice.
    """
    wanted_name = (name or "").strip().casefold()
    for existing in repo.list_funders(conn, org_id=org):
        if ignore_id and existing["id"] == ignore_id:
            continue
        if wanted_name and existing["name"].strip().casefold() == wanted_name:
            return existing
        if url and existing.get("url") and _same_page(existing["url"], url):
            return existing
    return None


def _already_have(existing: dict) -> str:
    """Why the add was refused, in a form that accounts for where it actually is.

    The remove list is the trap. A funder taken off the search is still on the list, just
    unticked and collapsed into a section further down — so "you already have this" reads
    as flatly wrong to somebody looking at the funders they can see. Say where it is.
    """
    if not existing["active"]:
        return (f'"{existing["name"]}" is already on your list, on the remove list '
                "further down this page. Tick it to start searching it again rather "
                "than adding it twice.")
    return (f'"{existing["name"]}" is already on your list. Edit that one instead — '
            "adding it twice means it gets read and scored twice every week.")

@api.get("/funders")
def list_funders(org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {"funders": repo.list_funders(conn, org_id=org),
                "sectors_available": list(SECTORS)}


@api.post("/funders", status_code=201)
def create_funder(body: FunderIn, org: str = Depends(current_org)) -> dict:
    data = _set(body)
    try:
        with session() as conn:
            clash = _duplicate_funder(conn, org, data.get("name"), data.get("url"))
            if clash:
                raise HTTPException(409, _already_have(clash))
            funder = repo.create_funder(conn, data, org_id=org)
            sharing = repo.get_settings(conn, org_id=org)["share_funders"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if sharing:
        _schedule_funder_checks(org)
    return {"funder": funder}


@api.put("/funders/{funder_id}")
def update_funder(funder_id: str, body: FunderIn,
                  org: str = Depends(current_org)) -> dict:
    changes = _set(body)
    with session() as conn:
        # Editing a funder onto another one's name or page is the same collision as
        # adding it twice, so it gets the same answer. `ignore_id` is what stops a plain
        # "save" on an unchanged row from reporting the row as a duplicate of itself.
        if "name" in changes or "url" in changes:
            clash = _duplicate_funder(conn, org, changes.get("name"),
                                      changes.get("url"), ignore_id=funder_id)
            if clash:
                raise HTTPException(409, _already_have(clash))
        updated = repo.update_funder(conn, funder_id, changes, org_id=org)
        sharing = repo.get_settings(conn, org_id=org)["share_funders"]
    if updated is None:
        raise HTTPException(404, "No such funder.")
    # A new address clears the old verdict (see `repo.update_funder`), so look at it
    # again — otherwise fixing a typo in a link would leave the funder marked unreachable
    # and unshared for good, with nothing the person could do about it.
    if sharing and "url" in changes:
        _schedule_funder_checks(org)
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


def _is_platform_admin(user) -> bool:
    """The boolean behind `require_admin`, for telling the UI whether to render the
    moderation queue at all. Same rule, same env var, no second definition — a UI check
    that could drift from the gate would eventually show a queue nobody can act on."""
    try:
        require_admin(user)
        return True
    except HTTPException:
        return False


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


@api.delete("/directory/{key}/import")
def remove_directory_list(key: str, org: str = Depends(current_org)) -> dict:
    """The exact reverse of the POST above — every funder this org has from list
    `key` comes off the list in one call, so the "34 funders" a card promised to
    add is also what it promises to take back."""
    with session() as conn:
        try:
            removed = remove_starter_list(conn, key, org)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"removed": removed, "funders": repo.list_funders(conn, org_id=org)}


# --- funders other nonprofits have shared -------------------------------------

@api.get("/directory/shared")
def read_shared_funders(org: str = Depends(current_org)) -> dict:
    """Hand-added funders from orgs that ticked "share the funders I add".

    Everything here is somebody else's suggestion, and the response says so in the shape
    of the data rather than trusting the UI to remember: each entry carries the sentence
    we can stand behind (`evidence`) and the date it was true, never a boolean called
    `verified`. See `app/funder_check.py` for what those checks can and cannot establish.
    """
    with session() as conn:
        return {"funders": repo.shared_funders(conn, org_id=org)}


class ShareReportIn(BaseModel):
    from_org: str = Field(min_length=1, max_length=64)
    funder_id: str = Field(min_length=1, max_length=64)
    reason: str = Field("", max_length=500)


@api.post("/directory/shared/report", status_code=201)
def report_shared(body: ShareReportIn, org: str = Depends(current_org)) -> dict:
    """Object to a shared funder — wrong, misleading, or not something to put in front of
    a nonprofit.

    **It is hidden from everybody the moment this is called**, before any admin looks.
    That is the deliberate direction to fail in: hiding a good funder for a few days
    costs one nonprofit one grants page they could add by hand anyway, and leaving a bad
    one up costs somebody an afternoon writing to nobody.

    The reporting org is recorded and never shown. Who objected to whom is exactly the
    kind of thing a small nonprofit sector would gossip about.
    """
    with session() as conn:
        out = repo.report_shared_funder(
            conn, funder_org=body.from_org, funder_id=body.funder_id,
            reported_by=org, reason=body.reason)
    log.info("shared funder %s/%s reported", body.from_org, body.funder_id)
    return {"reported": True, **out}


@api.get("/admin/reports", dependencies=[Depends(require_admin)])
def list_reports() -> dict:
    """The moderation queue, one card per reported funder. Crosses every tenant
    boundary, so it is gated by `FUNDWORTHY_ADMIN_EMAILS` alone — see `require_admin`.
    `counts` is what the tab's three stat boxes and filter pills read, computed here
    rather than three more round trips for numbers the list already has."""
    with session() as conn:
        groups = repo.all_reports(conn)
    counts = {"open": 0, "upheld": 0, "dismissed": 0}
    for g in groups:
        counts[g["status"]] = counts.get(g["status"], 0) + 1
    return {"reports": groups, "counts": counts}


class ResolveIn(BaseModel):
    uphold: bool
    funder_org: str = Field(min_length=1, max_length=64)
    funder_id: str = Field(min_length=1, max_length=128)


@api.post("/admin/reports/resolve", dependencies=[Depends(require_admin)])
def resolve_shared_report(body: ResolveIn, user=Depends(auth.require_user)) -> dict:
    """Take a reported funder down for good, or dismiss every open report against it
    and put it back in the pool — see `repo.resolve_report_group` for why this resolves
    the whole funder, not one report row."""
    with session() as conn:
        n = repo.resolve_report_group(conn, body.funder_org, body.funder_id,
                                      uphold=body.uphold,
                                      by=user.email if user else "local")
        if not n:
            raise HTTPException(404, "No open report for that funder.")
    return {"resolved": n, "upheld": body.uphold}


# --- bug reports ----------------------------------------------------------------

class BugReportIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    page: str = Field("", max_length=100)


@api.post("/bug-report")
async def submit_bug_report(body: BugReportIn, request: Request,
                            org: str = Depends(current_org),
                            user=Depends(auth.require_user)) -> dict:
    """Report a problem with the app itself, from the dashboard.

    Recorded locally FIRST, before GitHub is ever contacted, so a report is never
    lost even when the GitHub call fails — `bug_reports` already has the row, and
    auto-filing is a convenience layered on top of it, not the only copy. Filed
    against the install's own repo with an install-level token
    (`FUNDWORTHY_GITHUB_TOKEN` / `FUNDWORTHY_GITHUB_REPO`, see app/bugreport.py) —
    never a per-org secret, the same operational-channel pattern as
    `FUNDWORTHY_SHEET_ID` or `FUNDWORTHY_ADMIN_EMAILS`. Capped per org per day,
    because filing a real GitHub issue has a human cost a metered API call does not.
    """
    from . import bugreport

    with session() as conn:
        if (repo.count_recent_bug_reports(conn, org_id=org)
                >= bugreport.MAX_REPORTS_PER_ORG_PER_DAY):
            raise HTTPException(
                429,
                f"You've reported {bugreport.MAX_REPORTS_PER_ORG_PER_DAY} bugs in "
                "the last 24 hours — give it a bit before reporting more.")

        org_name = repo.get_settings(conn, org_id=org)["org_name"]
        reported_by = user.email if user else "local"
        title = body.title.strip()
        description = body.description.strip()
        page = body.page.strip()
        last_run = repo.latest_run(conn, org_id=org)

        report_id = repo.create_bug_report(
            conn, org_id=org, title=title, description=description, page=page,
            reported_by=reported_by)
    # The session above is closed — and its insert committed — before the network
    # call below, so a slow or hanging GitHub request never holds a write lock open
    # on the store.

    issue_body = bugreport.format_issue_body(
        description, org_name=org_name, org_id=org, reporter=reported_by, page=page,
        user_agent=request.headers.get("user-agent", ""),
        last_search=last_run["started_at"] if last_run else None)

    try:
        result = await bugreport.file_github_issue(title, issue_body)
    except bugreport.BugReportError as exc:
        with session() as conn:
            repo.record_bug_report_result(conn, report_id, error=str(exc))
        log.warning("bug report %s saved but could not be filed on GitHub: %s",
                   report_id, exc)
        # 200, not 500 — the report was saved even though auto-filing failed. That is
        # the honest, non-crashing outcome; the dashboard renders a fallback for it.
        return {"filed": False, "error": str(exc), "report_id": report_id}

    with session() as conn:
        repo.record_bug_report_result(
            conn, report_id, issue_url=result["issue_url"],
            issue_number=result["issue_number"])
    log.info("bug report %s filed as GitHub issue #%s", report_id,
             result["issue_number"])
    return {"filed": True, "issue_url": result["issue_url"],
           "issue_number": result["issue_number"], "report_id": report_id}


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
        org_name = repo.get_settings(conn, org_id=org)["org_name"]
    return Response(
        content=export.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        # Without this the browser renders the CSV as text instead of saving it.
        headers={"Content-Disposition":
                 f'attachment; filename="{export.filename(key, org_name)}"'},
    )


@api.get("/archive")
def read_archive(month: str | None = None, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        summary = archive.month_summary(conn, org_id=org)
        rows = repo.list_opportunities(conn, org_id=org, month=month) if month else []
        months = repo.available_months(conn, org_id=org)
        # The effort chip on every row is measured against the org's own hours-per-
        # application figure, so the archive has to carry it as well as the dashboard.
        # Without it this page would either invent a cap or drop the comparison, and
        # the archive renders the same component as This week.
        hours = repo.get_settings(conn, org_id=org).get("max_effort_hours")
        # One card per search, not one pooled list — see `repo.list_runs_for_month`.
        searches = repo.list_runs_for_month(conn, org_id=org, month=month) if month else []
    return {**summary, "months_available": months, "month": month,
            "opportunities": rows, "max_effort_hours": hours, "searches": searches}


# --- runs ---------------------------------------------------------------------

@api.get("/runs")
def list_runs(limit: int = 20, org: str = Depends(current_org)) -> dict:
    with session() as conn:
        return {"runs": repo.list_runs(conn, limit=limit, org_id=org)}


def _run_summary(run: dict | None) -> dict | None:
    """A run row without its reject list or its log. See the note at the /api/state call
    site: both are hundreds of rows nobody reads until they open something, and
    /api/state is fetched on every dashboard load. `GET /api/runs/{id}/rejects` and
    `GET /api/runs/current` serve them on demand."""
    if run is None:
        return None
    return {k: v for k, v in run.items() if k not in ("rejects", "log_tail")}


@api.get("/runs/{run_id}/rejects")
def run_rejects(run_id: str, reason: str | None = None, limit: int = 60,
                offset: int = 0, org: str = Depends(current_org)) -> dict:
    """Which candidates a run set aside, and why. Behind the stage boxes.

    Its own endpoint rather than a field on `/api/state`, because this is up to
    `models.MAX_REJECTS` rows of detail that nobody sees until they open a stage — and
    `/api/state` is fetched on every dashboard load. Putting it there would make the
    common path pay for the rare one.

    Grouped counts come back whole (they are small and the boxes need all of them); the
    rows themselves page, which is the "paginate server-side if a run ever exceeds it"
    the roadmap asks for.
    """
    with session() as conn:
        run = repo.get_run(conn, run_id, org_id=org)
    if run is None:
        raise HTTPException(404, "No such search.")

    rows = run.get("rejects") or []
    # Every reason present, with its true total from `rejected_by_filter` where we have
    # one. The two can legitimately disagree: the row list is capped, and the API
    # adapters report counts with no rows at all.
    counts = dict(run.get("rejected_by_filter") or {})
    by_reason: dict[str, dict] = {}
    for row in rows:
        g = by_reason.setdefault(row["reason"], {"reason": row["reason"],
                                                 "stage": row["stage"], "rows": 0})
        g["rows"] += 1
    groups = [{**g, "total": counts.get(g["reason"], g["rows"])}
              for g in by_reason.values()]
    # Reasons that were counted but produced no rows — the indexed databases aggregate
    # their own rejects. Shown, so the totals add up, and labelled as detail-free rather
    # than silently missing.
    #
    # NB the loop variable is `key`, not `reason`: `reason` is this function's filter
    # parameter, and rebinding it here left it holding the last counted reason, so every
    # unfiltered request came back filtered to whatever that happened to be. The groups
    # were right and the rows were one row, which is a confusing way to find out.
    for key, total in counts.items():
        if key not in by_reason:
            groups.append({"reason": key, "stage": 1, "rows": 0, "total": total})
    groups.sort(key=lambda g: (g["stage"], -g["total"]))

    if reason:
        rows = [r for r in rows if r["reason"] == reason]
    return {
        "groups": groups,
        "rejects": rows[offset:offset + limit],
        "shown": len(rows[offset:offset + limit]),
        "matching": len(rows),
        # True when the pipeline stopped recording rows but kept counting. The UI says
        # so rather than letting the numbers quietly disagree.
        "truncated": len(run.get("rejects") or []) >= MAX_REJECTS,
    }


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
    # While a run is going the live buffer is the log. Once it ends, that buffer is gone
    # within microseconds (the slot is reaped as the child exits), so fall back to what
    # `_persist_log` wrote onto the row — otherwise "Show the technical log" is empty for
    # every finished run, which is every run anybody actually wants to read it for.
    live = MANAGER.log_tail(org)
    return {"running": bool(mine), "run": run,
            "log": live or (run or {}).get("log_tail") or []}


@api.post("/runs", status_code=202)
def start_run(body: RunIn, org: str = Depends(current_org),
              user=Depends(auth.require_user)) -> dict:
    """The "Re-run search pipeline" button.

    The kill switch used to be re-checked here, separately from everything else that can
    stop a run. It is one of five now, all of them in `runner.preflight`, all phrased for
    the person reading them, and all returned by `GET /api/state` so the button can be
    disabled with the same sentence it would have failed with.
    """
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
            # The model picker's options come from the pipeline, so adding a model is
            # one edit in agent/score.py rather than two lists quietly drifting apart —
            # and a model offered here with no PRICING entry would abort a run.
            "model_choices": MODEL_CHOICES,
            "model_defaults": {"2": TRIAGE_MODEL, "3": SCORING_MODEL},
            # Same reasoning as model_choices above: the picker's options come from
            # the pipeline, so a level Fundworthy doesn't actually support can never
            # be offered in the UI in the first place.
            "effort_choices": EFFORT_CHOICES,
            "programs": repo.list_programs(conn, org_id=org),
            "funders": repo.list_funders(conn, org_id=org),
            "month": month_key(),
            "clear": [r for r in rows if not r["needs_human_check"]],
            "needs_check": [r for r in rows if r["needs_human_check"]],
            # Without the reject rows: they can be hundreds, they are only read when
            # somebody opens a stage box, and /api/state is fetched on every load.
            # GET /api/runs/{id}/rejects serves them.
            "latest_run": _run_summary(repo.latest_run(conn, org_id=org)),
            "running": bool(MANAGER.current_run_id_for(org)),
            "spend": repo.spend_summary(conn, org_id=org),
            # Why a search would not work, if it would not. Same list, same wording, as
            # the error POST /runs would raise — so the button can explain itself before
            # it is pressed instead of after.
            "blockers": preflight(conn, org_id=org),
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

def _require_admin(conn, org: str, user) -> str:
    """The uid of the caller, having established they administer this org.

    Server-side and unconditional. The dashboard hides Manage from everyone but the
    admin, which is courtesy — this is the part that decides, because a hidden button is
    not a permission check and removing a colleague is not undoable.
    """
    if user is None:
        # A local install has one org, no accounts, and nobody to be an admin over. The
        # person at the keyboard already owns the database file.
        return ""
    owner = org_owner(conn, org)
    if owner != user.uid:
        raise HTTPException(
            403, "Only your organization's admin can do that. Ask them to make the "
                 "change, or to hand the organization over to you.")
    return user.uid


@api.get("/org")
def read_org(org: str = Depends(current_org),
             user=Depends(auth.require_user)) -> dict:
    """Who is in your org, and the outstanding invitations."""
    with session() as conn:
        row = conn.execute("SELECT name FROM orgs WHERE id=?", (org,)).fetchone()
        owner = org_owner(conn, org)
        return {
            "org_id": org,
            "name": (row["name"] if row else "") or "",
            "members": org_members(conn, org),
            "invites": [i for i in list_invites(conn, org) if not i["redeemed_at"]],
            # Who *you* are, so the page can show the admin controls to one person and
            # not pretend the other three are one click from removing each other. On a
            # local install there is nobody to authenticate and one org, so the person at
            # the keyboard is the admin by definition.
            "you": user.uid if user else "",
            "you_are_admin": (user is None) or (owner == user.uid),
            # Different thing entirely from `you_are_admin`, which is about this org.
            # This is the install operator — the only person who can take a reported
            # funder down — and it is gated by FUNDWORTHY_ADMIN_EMAILS, never by being
            # somebody's org admin.
            "platform_admin": _is_platform_admin(user),
        }


@api.get("/orgs/mine")
def read_my_orgs(user=Depends(auth.require_user)) -> dict:
    """Every organization this person can switch into, for the sidebar switcher.

    Not gated on `current_org` — that resolves the *active* org, and this endpoint's
    whole job is to list every org that is not necessarily the active one. On a local
    install there is no user and exactly one org, so the switcher has nothing to do; the
    dashboard does not call this route in that mode.
    """
    if user is None:
        return {"orgs": []}
    with session() as conn:
        return {"orgs": my_orgs(conn, user.uid)}


class SwitchOrgIn(BaseModel):
    org_id: str = Field(min_length=1, max_length=128)


@api.post("/org/switch")
def switch_org(body: SwitchOrgIn, user=Depends(auth.require_user)) -> dict:
    """Change which organization's data this person is looking at.

    The only handler that takes an org id from the client — see the note on
    `current_org` above for why that is safe here specifically: `db.switch_active_org`
    checks a real membership row exists before writing anything, so this can only ever
    move somebody to an org they already belong to, never anywhere else.
    """
    if user is None:
        raise HTTPException(
            400, "Switching organizations needs sign-in, which this install has off.")
    with session() as conn:
        try:
            switch_active_org(conn, user.uid, body.org_id)
        except ValueError as exc:
            raise HTTPException(403, "You are not a member of that organization.") from exc
    return {"org_id": body.org_id}


class MemberIn(BaseModel):
    uid: str = Field(min_length=1, max_length=128)


@api.delete("/org/members/{uid}")
def remove_org_member(uid: str, org: str = Depends(current_org),
                      user=Depends(auth.require_user)) -> dict:
    """Take a colleague out of this organization. Admin only.

    They lose everything of this org's at once — findings, funders, and the saved API
    key — because every route resolves their org from the `users` row this deletes. Their
    next sign-in provisions a fresh empty org and they are walked through onboarding like
    anybody new.
    """
    with session() as conn:
        me = _require_admin(conn, org, user)
        if uid == me:
            raise HTTPException(
                400, "You cannot remove yourself. Hand the organization to somebody "
                     "else first, or delete your account from the bottom of Settings.")
        target = conn.execute("SELECT email FROM users WHERE uid=? AND org_id=?",
                              (uid, org)).fetchone()
        if target is None:
            raise HTTPException(404, "That person is not in your organization.")
        remove_member(conn, uid, org)
    log.info("%s removed %s from org %s",
             user.email if user else "local", target["email"], org)
    return {"removed": target["email"]}


@api.post("/org/transfer")
def transfer_org(body: MemberIn, org: str = Depends(current_org),
                 user=Depends(auth.require_user)) -> dict:
    """Hand the organization to another member. Admin only, and one-way.

    The old admin stays a member and keeps working; they simply cannot remove people any
    more. That is the point of transferring rather than deleting: somebody leaving a
    nonprofit should be able to pass the keys on before they go.
    """
    with session() as conn:
        _require_admin(conn, org, user)
        try:
            set_org_owner(conn, org, body.uid)
        except ValueError as exc:
            raise HTTPException(404, "That person is not in your organization.") from exc
        new_owner = conn.execute("SELECT email FROM users WHERE uid=?",
                                 (body.uid,)).fetchone()
    log.info("org %s handed from %s to %s", org,
             user.email if user else "local", new_owner["email"])
    return {"admin": new_owner["email"]}


@api.delete("/account")
def delete_own_account(org: str = Depends(current_org),
                       user=Depends(auth.require_user)) -> dict:
    """Delete your own account and leave your organization.

    Two refusals, both about not stranding other people:

      - The admin of an org with colleagues in it must hand it over first. Otherwise the
        org's last admin walks out and nobody left can remove anyone or invite anyone.
        (An admin who is the *only* member is fine — there is nobody to strand.)
      - A local install has no accounts to delete.

    If you are the last one out, `strand_org` clears the findings, the run log and the
    saved API key, and deliberately keeps the funder list — see its docstring for why
    that asymmetry is the point rather than an oversight.

    The Firebase sign-in goes too, so "delete my account" does not quietly mean "delete
    my data and keep your email address on file". It is reported separately in the
    response because it can fail on its own — Firebase refuses to delete on a stale
    sign-in — and the honest answer then is to say the data is gone and the sign-in is
    not, rather than to claim both.
    """
    if user is None:
        raise HTTPException(
            400, "This install has no accounts, so there is nothing to delete. Your data "
                 "is the database file on this computer.")

    with session() as conn:
        others = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE org_id=? AND uid<>?",
            (org, user.uid)).fetchone()["n"]
        if others and org_owner(conn, org) == user.uid:
            raise HTTPException(
                409,
                "You are this organization's admin and other people are still in it. "
                "Hand the organization to one of them first, then delete your account.")

        cleared = {}
        remove_member(conn, user.uid, org)
        if not others:
            cleared = {"findings_and_runs_deleted": True, "funders_kept": True}

    # Then the sign-in itself, and **only in this order**. If this fails the person can
    # still sign in and lands in a fresh empty org — harmless, and they can try again.
    # Reversed, a failure would lock somebody out of an account whose data is still here.
    sign_in = auth.delete_firebase_account(user.token)

    log.info("account deleted: %s (org %s, %d other member(s) remain, sign-in: %s)",
             user.email, org, others, sign_in.value)
    return {"deleted": user.email, "sign_in": sign_in.value, **cleared}


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
    """Redeem an invitation and switch into that colleague's organization.

    Note this deliberately does **not** depend on `current_org`: resolving the caller's
    current org would provision an empty home org for a brand-new sign-in a moment
    before this ever needed one.

    Joining **adds** a second organization — see `db.redeem_invite` — rather than moving
    anybody out of their first. Nothing here can strand an org or need an admin to hand
    anything over first, because nobody is leaving.
    """
    if user is None:
        raise HTTPException(
            400, "Joining an organization needs sign-in, which this install has off.")
    try:
        with session() as conn:
            result = redeem_invite(conn, body.code, user.uid, user.email)
    except InviteError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"joined": True, **result}


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

        # GET *and* HEAD. FastAPI, unlike a plain Starlette route, does not add HEAD
        # alongside GET, so every page and every static file answered `405 Method Not
        # Allowed` to a HEAD — including robots.txt and sitemap.xml. HTTP requires HEAD
        # wherever GET is served (it is defined as GET without the body), and the clients
        # that use it are exactly the ones we care about here: crawlers checking a file's
        # type and size before downloading it, and uptime monitors, which read a 405 as
        # the site being down.
        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
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
