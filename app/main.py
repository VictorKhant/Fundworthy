"""The REST API and the static host for the dashboard. (docs/PLAN.md §1)

Runs on Mauri's machine, not on the internet. That is a deliberate scoping decision,
not an oversight: CLAUDE.md §3 rules out accounts and auth for v1, and the honest way to
keep that promise while also storing an API key is to not be reachable from the network
in the first place. The server binds to localhost, and `HANDOFF.md` says what has to
change before it is ever exposed — that is a real decision RISE gets to make, with the
tradeoff written down, rather than a default we slid into.

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
    GET    /api/opportunities          this month's findings, in her reading order
    GET    /api/archive                the archive, by month
    GET    /api/runs                   run history
    POST   /api/runs                   ← the "Re-run search pipeline" button
    POST   /api/runs/stop              ← the stop button
    GET    /api/runs/current           live progress while one is going

There is no endpoint that returns the API key. That is not an omission.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import archive, repo, secrets
from .db import SECTORS, init_db, month_key, session
from .runner import MANAGER

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dashboard" / "dist"

api = APIRouter(prefix="/api")


# --- request bodies -----------------------------------------------------------

class SettingsIn(BaseModel):
    min_award: int | None = Field(None, ge=0)
    min_deadline_runway_days: int | None = Field(None, ge=0, le=365)
    max_opportunities: int | None = Field(None, ge=1, le=100)
    run_budget_usd: float | None = Field(None, gt=0, le=20)
    enabled: bool | None = None
    sectors_active: list[str] | None = None
    search_beyond_partners: bool | None = None


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
    tier: int | None = Field(None, ge=1, le=3)
    programs: list[str] | None = None
    notes: str | None = None


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

@api.get("/settings")
def read_settings() -> dict:
    with session() as conn:
        stored = secrets.read_api_key(conn)
        return {
            "settings": repo.get_settings(conn),
            # A hint, never the key. There is no path that returns the secret.
            "api_key_hint": secrets.mask(stored),
            "has_api_key": bool(stored),
            "sectors_available": list(SECTORS),
        }


@api.put("/settings")
def write_settings(body: SettingsIn) -> dict:
    changes = _set(body)
    if "sectors_active" in changes:
        unknown = [s for s in changes["sectors_active"] if s not in SECTORS]
        if unknown:
            raise HTTPException(400, f"Unknown sector(s): {', '.join(unknown)}")
    with session() as conn:
        return {"settings": repo.update_settings(conn, changes)}


@api.post("/settings/api-key")
def save_api_key(body: ApiKeyIn) -> dict:
    key = body.api_key.strip()
    with session() as conn:
        secrets.store_api_key(conn, key)
    log.info("API key saved (%s)", secrets.mask(key))
    return {"has_api_key": True, "api_key_hint": secrets.mask(key)}


@api.delete("/settings/api-key")
def delete_api_key() -> dict:
    with session() as conn:
        secrets.clear_api_key(conn)
    return {"has_api_key": False, "api_key_hint": None}


@api.post("/settings/api-key/test")
def test_api_key(body: ApiKeyTestIn | None = None) -> dict:
    """Check a key works before trusting it. One token, so effectively free.

    Accepts a key in the body to test before saving, or falls back to the saved one —
    so "is the key I already have still good?" is answerable without re-typing it.
    """
    key = (body.api_key.strip() if body and body.api_key else None)
    if not key:
        with session() as conn:
            key = secrets.read_api_key(conn)
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
def list_programs() -> dict:
    with session() as conn:
        return {"programs": repo.list_programs(conn)}


@api.post("/programs", status_code=201)
def create_program(body: ProgramIn) -> dict:
    try:
        with session() as conn:
            return {"program": repo.create_program(conn, _set(body))}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.put("/programs/{program_id}")
def update_program(program_id: str, body: ProgramIn) -> dict:
    with session() as conn:
        updated = repo.update_program(conn, program_id, _set(body))
    if updated is None:
        raise HTTPException(404, "No such program.")
    return {"program": updated}


@api.delete("/programs/{program_id}")
def delete_program(program_id: str) -> dict:
    with session() as conn:
        if not repo.delete_program(conn, program_id):
            raise HTTPException(404, "No such program.")
    return {"deleted": program_id}


@api.post("/programs/draft")
async def draft_program(body: DraftIn) -> dict:
    """The assistant. Returns a draft for Mauri to review — saves nothing."""
    from .assistant import AssistantError, draft_program_card

    with session() as conn:
        key = secrets.effective_api_key(conn)
    try:
        return {"draft": await draft_program_card(body.url.strip(), key)}
    except AssistantError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("assistant failed")
        raise HTTPException(500, f"The assistant could not finish ({type(exc).__name__}).") from exc


# --- funders ------------------------------------------------------------------

@api.get("/funders")
def list_funders() -> dict:
    with session() as conn:
        return {"funders": repo.list_funders(conn), "sectors_available": list(SECTORS)}


@api.post("/funders", status_code=201)
def create_funder(body: FunderIn) -> dict:
    try:
        with session() as conn:
            return {"funder": repo.create_funder(conn, _set(body))}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.put("/funders/{funder_id}")
def update_funder(funder_id: str, body: FunderIn) -> dict:
    with session() as conn:
        updated = repo.update_funder(conn, funder_id, _set(body))
    if updated is None:
        raise HTTPException(404, "No such funder.")
    return {"funder": updated}


@api.delete("/funders/{funder_id}")
def delete_funder(funder_id: str) -> dict:
    with session() as conn:
        if not repo.delete_funder(conn, funder_id):
            raise HTTPException(404, "No such funder.")
    return {"deleted": funder_id}


# --- findings -----------------------------------------------------------------

@api.get("/opportunities")
def list_opportunities(month: str | None = None, run_id: str | None = None) -> dict:
    with session() as conn:
        rows = repo.list_opportunities(conn, month=month or month_key(), run_id=run_id)
    return {
        "month": month or month_key(),
        "opportunities": rows,
        # Split out so the UI never has to re-derive Mauri's reading order. She asked
        # for the clean results first and the ambiguous ones at the bottom.
        "clear": [r for r in rows if not r["needs_human_check"]],
        "needs_check": [r for r in rows if r["needs_human_check"]],
    }


@api.get("/archive")
def read_archive(month: str | None = None) -> dict:
    with session() as conn:
        summary = archive.month_summary(conn)
        rows = repo.list_opportunities(conn, month=month) if month else []
        months = repo.available_months(conn)
    return {**summary, "months_available": months,
            "month": month, "opportunities": rows}


# --- runs ---------------------------------------------------------------------

@api.get("/runs")
def list_runs(limit: int = 20) -> dict:
    with session() as conn:
        return {"runs": repo.list_runs(conn, limit=limit)}


@api.get("/runs/current")
def current_run() -> dict:
    with session() as conn:
        run = repo.get_run(conn, MANAGER.current_run_id()) if MANAGER.current_run_id() \
            else repo.latest_run(conn)
    return {"running": MANAGER.is_running, "run": run, "log": MANAGER.log_tail()}


@api.post("/runs", status_code=202)
def start_run(body: RunIn) -> dict:
    """The "Re-run search pipeline" button."""
    with session() as conn:
        if not repo.get_settings(conn)["enabled"]:
            raise HTTPException(
                409, "The agent is switched off. Turn it back on in Settings first.")
    try:
        run_id = MANAGER.start(no_llm=body.no_llm, budget=body.budget,
                               max_opportunities=body.max_opportunities)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id, "running": True}


@api.post("/runs/stop")
def stop_run() -> dict:
    return {"stopped": MANAGER.stop()}


# --- one call for the whole dashboard -----------------------------------------

@api.get("/state")
def state() -> dict:
    """Everything the main page needs. One request instead of six, so the dashboard
    cannot render itself half-populated while the rest arrives."""
    with session() as conn:
        stored = secrets.read_api_key(conn)
        rows = repo.list_opportunities(conn, month=month_key())
        return {
            "settings": repo.get_settings(conn),
            "has_api_key": bool(stored),
            "api_key_hint": secrets.mask(stored),
            "sectors_available": list(SECTORS),
            "programs": repo.list_programs(conn),
            "funders": repo.list_funders(conn),
            "month": month_key(),
            "clear": [r for r in rows if not r["needs_human_check"]],
            "needs_check": [r for r in rows if r["needs_human_check"]],
            "latest_run": repo.latest_run(conn),
            "running": MANAGER.is_running,
        }


@api.get("/health")
def health() -> dict:
    return {"ok": True}


# --- app ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("RISE Fund Finder ready.")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RISE Fund Finder",
        description="Local control surface for RISE San Diego's funding agent.",
        version="2.0.0",
        docs_url="/api/docs",
        lifespan=lifespan,
    )

    # The Vite dev server runs on another port during development. Localhost only —
    # this is not an invitation for anything else to call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api)

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            """Serve the built dashboard, falling back to index.html for client routes."""
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
