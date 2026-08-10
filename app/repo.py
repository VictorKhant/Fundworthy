"""CRUD over the SQLite store. (CLAUDE.md)

Plain functions taking an open connection, so the API layer, the pipeline runner and
the tests all use exactly the same code path. No ORM, no session magic, nothing that
behaves differently under a background thread than it does under a request.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .db import (DEFAULT_SETTINGS, dumps, loads, month_key, now_iso)
from .secrets import SETTING_NAME as API_KEY_SETTING

log = logging.getLogger(__name__)

# Settings the browser is allowed to read and write. The API key is deliberately not in
# this set — it has its own write-only path in app/secrets.py.
PUBLIC_SETTINGS = tuple(DEFAULT_SETTINGS.keys())

_INT_SETTINGS = {"min_award", "min_deadline_runway_days", "max_opportunities",
                 "schedule_hour", "max_effort_hours"}
_FLOAT_SETTINGS = {"run_budget_usd", "monthly_budget_usd"}
_BOOL_SETTINGS = {"enabled", "schedule_enabled", "search_beyond_partners",
                  "onboarding_done", "share_funders", "ultra_mode"}
_JSON_SETTINGS = {"sectors_active"}


# --- settings -----------------------------------------------------------------

def get_settings(conn, *, org_id: str) -> dict[str, Any]:
    """Typed settings, with defaults filled in for anything missing."""
    rows = {r["key"]: r["value"] for r in
            conn.execute("SELECT key, value FROM settings WHERE org_id=?", (org_id,))}
    out: dict[str, Any] = {}
    for key in PUBLIC_SETTINGS:
        raw = rows.get(key, DEFAULT_SETTINGS.get(key))
        out[key] = _coerce(key, raw)
    return out


def _coerce(key: str, raw: Any) -> Any:
    if raw is None:
        raw = DEFAULT_SETTINGS.get(key)
    try:
        if key in _INT_SETTINGS:
            return int(float(str(raw)))
        if key in _FLOAT_SETTINGS:
            return float(raw)
        if key in _BOOL_SETTINGS:
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        if key in _JSON_SETTINGS:
            return loads(raw, [])
    except (TypeError, ValueError):
        log.warning("setting %s=%r is unreadable — falling back to the default", key, raw)
        return _coerce(key, DEFAULT_SETTINGS.get(key))
    return raw


def update_settings(conn, changes: dict[str, Any], *, org_id: str) -> dict[str, Any]:
    """Write only known keys. An unknown key is ignored, not stored — otherwise the
    settings table becomes a junk drawer that nothing validates."""
    stamp = now_iso()
    for key, value in changes.items():
        if key not in PUBLIC_SETTINGS:
            log.warning("ignoring unknown setting %r", key)
            continue
        if key in _BOOL_SETTINGS:
            stored = "1" if value in (True, 1, "1", "true", "yes", "on") else "0"
        elif key in _JSON_SETTINGS:
            stored = dumps(value if isinstance(value, list) else [])
        else:
            stored = str(value)
        conn.execute(
            "INSERT INTO settings(org_id, key, value, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(org_id, key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (org_id, key, stored, stamp),
        )
    return get_settings(conn, org_id=org_id)


# --- programs -----------------------------------------------------------------

_PROGRAM_FIELDS = ("name", "summary", "what_it_funds", "keywords", "funder_types",
                   "search_queries", "min_award", "active", "source_url",
                   "drafted_by_ai", "reviewed_by_human")
_PROGRAM_JSON = {"keywords", "funder_types", "search_queries"}
_PROGRAM_BOOL = {"active", "drafted_by_ai", "reviewed_by_human"}


def _program_out(row) -> dict:
    d = dict(row)
    for f in _PROGRAM_JSON:
        d[f] = loads(d.get(f), [])
    for f in _PROGRAM_BOOL:
        d[f] = bool(d.get(f))
    return d


def list_programs(conn, *, org_id: str, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM programs WHERE org_id=?"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY active DESC, name"
    return [_program_out(r) for r in conn.execute(sql, (org_id,))]


def get_program(conn, program_id: str, *, org_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM programs WHERE id=? AND org_id=?",
                       (program_id, org_id)).fetchone()
    return _program_out(row) if row else None


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()
    return slug[:40] or "PROGRAM"


def create_program(conn, data: dict, *, org_id: str) -> dict:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("a program needs a name")

    slug = str(data.get("slug") or slugify(name))
    # Two cards called "RISE Arts" is a data bug that only shows up weeks later as a
    # program silently not being searched. Disambiguate at write time instead.
    #
    # Scoped to the org: slugs only have to be unique within one nonprofit's own card
    # list. Comparing against every org's slugs would leak the shape of other orgs'
    # programs — the second org to create "Arts Education" would get "ARTS_EDUCATION_2"
    # and no explanation for the number.
    existing = {r["slug"] for r in
                conn.execute("SELECT slug FROM programs WHERE org_id=?", (org_id,))}
    base, n = slug, 2
    while slug in existing:
        slug, n = f"{base}_{n}", n + 1

    program_id = uuid.uuid4().hex[:16]
    stamp = now_iso()
    conn.execute(
        """INSERT INTO programs(
               org_id, id, name, slug, summary, what_it_funds, keywords, funder_types,
               search_queries, min_award, active, source_url, drafted_by_ai,
               reviewed_by_human, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            org_id, program_id, name, slug,
            str(data.get("summary", "")), str(data.get("what_it_funds", "")),
            dumps(data.get("keywords") or []), dumps(data.get("funder_types") or []),
            dumps(data.get("search_queries") or []),
            _nullable_int(data.get("min_award")),
            1 if data.get("active") else 0,
            str(data.get("source_url", "")),
            1 if data.get("drafted_by_ai") else 0,
            1 if data.get("reviewed_by_human") else 0,
            stamp, stamp,
        ),
    )
    return get_program(conn, program_id, org_id=org_id)  # type: ignore[return-value]


def program_is_empty(card: dict) -> bool:
    """A card with nothing in it for the model to match against.

    `summary` and `keywords` are the two fields `agent/score.py: org_context` actually
    puts in the prompt. A card with neither contributes its name and nothing else, and
    the scoring prompt has to fall back to "(No description recorded yet. Judge fit
    conservatively…)" — so ticking one does not narrow the search, it just adds a line
    of noise to every candidate.
    """
    return not str(card.get("summary") or "").strip() and not (card.get("keywords") or [])


def update_program(conn, program_id: str, changes: dict, *, org_id: str) -> dict | None:
    current = get_program(conn, program_id, org_id=org_id)
    if current is None:
        return None

    # An empty card cannot be ticked. The UI renders one as dashed and un-tickable and
    # opens the editor instead, but that is a UI affordance and this is the rule: a
    # direct PUT, the CLI, or a future integration must not be able to activate a card
    # the scorer can do nothing with.
    #
    # Checked against the card as it will be AFTER this write, not as it is now, so
    # filling in a summary and ticking it in one request is allowed — which is exactly
    # what saving the editor does.
    after = {**current, **{k: v for k, v in changes.items() if k in _PROGRAM_FIELDS}}
    if after.get("active") and program_is_empty(after):
        raise ValueError(
            f'"{after.get("name") or "This program"}" has no description yet, so there '
            "is nothing for the researcher to match grants against. Add a summary or "
            "some keywords — or paste the program's web page and let the assistant "
            "fill it in — and then tick it."
        )

    sets, values = [], []
    for field in _PROGRAM_FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field in _PROGRAM_JSON:
            value = dumps(value if isinstance(value, list) else [])
        elif field in _PROGRAM_BOOL:
            value = 1 if value else 0
        elif field == "min_award":
            value = _nullable_int(value)
        else:
            value = str(value)
        sets.append(f"{field}=?")
        values.append(value)
    if sets:
        sets.append("updated_at=?")
        values.extend([now_iso(), program_id, org_id])
        conn.execute(
            f"UPDATE programs SET {', '.join(sets)} WHERE id=? AND org_id=?", values)
    return get_program(conn, program_id, org_id=org_id)


def delete_program(conn, program_id: str, *, org_id: str) -> bool:
    cur = conn.execute("DELETE FROM programs WHERE id=? AND org_id=?",
                       (program_id, org_id))
    return cur.rowcount > 0


# --- funders ------------------------------------------------------------------

_FUNDER_FIELDS = ("name", "url", "sector", "funder_type", "warm", "active",
                  "blocked", "tier", "confidence", "region", "programs", "notes",
                  "exclude_reason")


def _funder_out(row) -> dict:
    d = dict(row)
    d["programs"] = loads(d.get("programs"), [])
    d["warm"] = bool(d.get("warm"))
    d["active"] = bool(d.get("active"))
    # **Tri-state, and it has to survive the trip.** NULL means nobody has looked yet,
    # which is not the same as failing — so this cannot collapse to a plain bool.
    #
    # It also cannot stay as SQLite's 1/0. Those cross to the browser as integers, and
    # `check_ok === true` is false for `1`, so the Settings page computed "0 of 2 shared"
    # while the database held one pass and one failure. Same family of bug as
    # `share_funders` being stored as the string "True": a value crossing the boundary
    # with a type that was assumed rather than checked.
    if d.get("check_ok") is not None:
        d["check_ok"] = bool(d["check_ok"])
    d["blocked"] = bool(d.get("blocked"))
    return d


def list_funders(conn, *, org_id: str, active_only: bool = False,
                 include_blocked: bool = True) -> list[dict]:
    sql = "SELECT * FROM funders WHERE org_id=?"
    if active_only:
        # A blocked funder is never searched, so "active" has to mean both.
        sql += " AND active=1 AND blocked=0"
    elif not include_blocked:
        sql += " AND blocked=0"
    # Alphabetical, case-insensitively. It used to be `warm DESC, name` — partners
    # first — which is exactly the priority the stakeholder asked us to drop. NOCASE
    # because SQLite's default is byte order, which puts every capitalised name above
    # every lowercase one and reads as unsorted to a person.
    sql += " ORDER BY name COLLATE NOCASE"
    return [_funder_out(r) for r in conn.execute(sql, (org_id,))]


def excluded_funder_names(conn, *, org_id: str) -> set[str]:
    """Funders on the remove list, casefolded, for result-level filtering.

    Skipping them at the crawl is the cheap half and catches most of it. But the two
    indexed databases return grants from every funder in the state, so an excluded
    funder can still arrive through Grants.gov or the CA portal — which would put
    exactly the opportunity they said they do not want back on their list, by a different
    door. Both doors have to be closed.
    """
    return {
        str(r["name"]).strip().casefold()
        for r in conn.execute(
            "SELECT name FROM funders WHERE (active=0 OR blocked=1) AND org_id=?",
            (org_id,))
    }


def blocked_funder_keys(conn, *, org_id: str) -> set[str]:
    """Blocked funders, by casefolded name and by casefolded URL.

    Both, because the three places that offer a funder identify it differently: a
    researched list matches on the derived id, the shared directory dedupes on URL, and
    a person types a name. Matching on one of those lets the other two put a blocked
    funder back in front of somebody who explicitly took it away.
    """
    keys: set[str] = set()
    for r in conn.execute("SELECT name, url FROM funders WHERE blocked=1 AND org_id=?",
                          (org_id,)):
        keys.add(str(r["name"] or "").strip().casefold())
        url = str(r["url"] or "").strip().rstrip("/").casefold()
        if url:
            keys.add(url)
    return keys


def get_funder(conn, funder_id: str, *, org_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM funders WHERE id=? AND org_id=?",
                       (funder_id, org_id)).fetchone()
    return _funder_out(row) if row else None


def create_funder(conn, data: dict, *, org_id: str) -> dict:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("a funder needs a name")
    funder_id = hashlib.sha256(name.casefold().encode()).hexdigest()[:16]
    stamp = now_iso()
    conn.execute(
        """INSERT INTO funders(
               org_id, id, name, url, sector, funder_type, warm, active, tier,
               confidence, region, programs, notes, added_by, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'user',?,?)
           ON CONFLICT(org_id, id) DO UPDATE SET
               url=excluded.url, sector=excluded.sector,
               funder_type=excluded.funder_type, warm=excluded.warm,
               active=excluded.active, region=excluded.region,
               programs=excluded.programs,
               notes=excluded.notes, updated_at=excluded.updated_at""",
        (
            org_id, funder_id, name, data.get("url"),
            str(data.get("sector", "other")), str(data.get("funder_type", "other")),
            1 if data.get("warm") else 0,
            0 if data.get("active") is False else 1,
            int(data.get("tier", 1) or 1), int(data.get("confidence", 1) or 1),
            str(data.get("region", "")),
            dumps(data.get("programs") or []), str(data.get("notes", "")),
            stamp, stamp,
        ),
    )
    return get_funder(conn, funder_id, org_id=org_id)  # type: ignore[return-value]


def update_funder(conn, funder_id: str, changes: dict, *, org_id: str) -> dict | None:
    if get_funder(conn, funder_id, org_id=org_id) is None:
        return None
    sets, values = [], []
    for field in _FUNDER_FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field == "programs":
            value = dumps(value if isinstance(value, list) else [])
        elif field in {"warm", "active", "blocked"}:
            # `blocked` belongs here and not in the `str(value)` fallback below, which
            # would store the literal "True" in an INTEGER column — so `blocked=1` never
            # matches and a funder somebody blocked keeps being searched and re-offered.
            # Same family as `share_funders` stored as "True": a value crossing a
            # boundary with a type that was assumed rather than checked.
            value = 1 if value else 0
        elif field in {"tier", "confidence"}:
            value = int(value or 1)
        elif field == "url":
            value = value or None
        else:
            value = str(value)
        sets.append(f"{field}=?")
        values.append(value)
    if sets:
        # A new address is a new page, so the old verdict is about something else.
        # Without this a funder whose URL failed the check once could never recover:
        # `recheck_shared` only picks up rows with `checked_at IS NULL`, so fixing a typo
        # would leave it permanently marked unreachable and permanently unshared, with
        # nothing the person could do about it.
        if "url" in changes:
            sets += ["check_ok=NULL", "check_note=''", "checked_at=NULL"]
        sets.append("updated_at=?")
        values.extend([now_iso(), funder_id, org_id])
        conn.execute(
            f"UPDATE funders SET {', '.join(sets)} WHERE id=? AND org_id=?", values)
    return get_funder(conn, funder_id, org_id=org_id)


def delete_funder(conn, funder_id: str, *, org_id: str) -> bool:
    cur = conn.execute("DELETE FROM funders WHERE id=? AND org_id=?",
                       (funder_id, org_id))
    return cur.rowcount > 0


# --- opportunities ------------------------------------------------------------

_OPP_JSON = {"program_match", "service_areas"}


def _opp_out(row) -> dict:
    d = dict(row)
    for f in _OPP_JSON:
        d[f] = loads(d.get(f), [])
    d["verified"] = bool(d.get("verified"))
    d["needs_human_check"] = bool(d.get("needs_human_check"))
    d["days_left"] = _days_left(d.get("deadline"))
    return d


def _days_left(deadline: str | None) -> int | None:
    if not deadline:
        return None
    try:
        return (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return None


def save_opportunity(conn, opp, run_id: str | None = None, *, org_id: str) -> None:
    """Upsert one Opportunity. Re-running the same week updates rather than duplicates."""
    d = opp.to_dict()
    stamp = now_iso()
    conn.execute(
        """INSERT INTO opportunities(
               org_id, id, run_id, month_key, found_on, title, funder, source_url,
               apply_url,
               award_min, award_max, award_typical, deadline, deadline_type,
               estimated_effort_hours, program_match, score,
               fit_score, award_score, timing_score, score_rationale,
               funder_type, service_areas, geography,
               confidence_pct, contact_note, verified, needs_human_check,
               section, source_kind, application_lead_time_days, time_to_funds_days,
               fetched_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(org_id, id) DO UPDATE SET
               run_id=excluded.run_id, score=excluded.score,
               fit_score=excluded.fit_score, award_score=excluded.award_score,
               timing_score=excluded.timing_score,
               score_rationale=excluded.score_rationale,
               apply_url=excluded.apply_url,
               award_min=excluded.award_min, award_max=excluded.award_max,
               award_typical=excluded.award_typical, deadline=excluded.deadline,
               deadline_type=excluded.deadline_type,
               estimated_effort_hours=excluded.estimated_effort_hours,
               program_match=excluded.program_match,
               funder_type=excluded.funder_type,
               service_areas=excluded.service_areas, geography=excluded.geography,
               confidence_pct=excluded.confidence_pct,
               contact_note=excluded.contact_note, verified=excluded.verified,
               needs_human_check=excluded.needs_human_check,
               section=excluded.section, source_kind=excluded.source_kind,
               application_lead_time_days=excluded.application_lead_time_days,
               time_to_funds_days=excluded.time_to_funds_days,
               fetched_at=excluded.fetched_at""",
        (
            org_id, d["id"], run_id, month_key(), d.get("found_on") or stamp[:10],
            d["title"], d["funder"], d["source_url"],
            d.get("apply_url"),
            d["award_min"], d["award_max"], d.get("award_typical"),
            d["deadline"], d.get("deadline_type", "unknown"),
            d["estimated_effort_hours"], dumps(d["program_match"]),
            d["score"],
            d.get("fit_score"), d.get("award_score"), d.get("timing_score"),
            d["score_rationale"],
            d.get("funder_type", "unknown"), dumps(d.get("service_areas") or []),
            d.get("geography"),
            d.get("confidence_pct"), d.get("contact_note"),
            int(d["verified"]), int(d["needs_human_check"]),
            d["section"], d.get("source_kind", "funder_page"),
            d.get("application_lead_time_days"), d.get("time_to_funds_days"),
            d["fetched_at"],
        ),
    )


def list_opportunities(conn, *, org_id: str, month: str | None = None,
                       run_id: str | None = None) -> list[dict]:
    """the user's reading order, enforced in SQL so every surface agrees.

    Two rules now, and the second one used to be three:

      1. Anything carrying a claim we could NOT verify against the page sinks to the
         bottom. That is what needs_human_check means since it was tightened — a real
         accuracy concern, not merely a field the funder left blank.
      2. Everything else ranks by score, highest first. Full stop.

    What was removed and why: the order used to put rows with a sourced award amount
    above rows without one. That made sense when "no amount" meant "we never paid to
    score it". Sonnet now scores every candidate, so the rule had quietly turned into
    "rank by whether the funder happened to publish a number" — which put a score-18
    opportunity above a score-65 in the last real run, because the 18 had a figure on
    its page and the 65 did not.
    """
    where, params = ["org_id=?"], [org_id]
    if month:
        where.append("month_key=?")
        params.append(month)
    if run_id:
        where.append("run_id=?")
        params.append(run_id)
    sql = "SELECT * FROM opportunities WHERE " + " AND ".join(where)
    sql += " ORDER BY needs_human_check ASC, score DESC, funder ASC"
    return [_opp_out(r) for r in conn.execute(sql, params)]


def available_months(conn, *, org_id: str) -> list[str]:
    return [r["month_key"] for r in conn.execute(
        "SELECT DISTINCT month_key FROM opportunities WHERE org_id=? "
        "ORDER BY month_key DESC", (org_id,))]


# --- runs ---------------------------------------------------------------------

def create_run(conn, run_id: str | None = None, *, org_id: str,
               started_by: str | None = None, trigger: str = "manual") -> str:
    run_id = run_id or uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO runs(org_id, id, started_by, trigger, started_at, status) "
        "VALUES(?,?,?,?,?, 'running')",
        (org_id, run_id, started_by, trigger, now_iso()),
    )
    return run_id


def update_run(conn, run_id: str, **fields) -> None:
    if not fields:
        return
    for json_field in ("rejected_by_filter", "notes", "progress", "source_health",
                       "rejects", "usd_by_stage", "log_tail",
                       "programs_snapshot", "funder_groups"):
        if json_field in fields and not isinstance(fields[json_field], str):
            fields[json_field] = dumps(fields[json_field])
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE runs SET {sets} WHERE id=?", [*fields.values(), run_id])


def _run_out(row) -> dict:
    d = dict(row)
    d["rejected_by_filter"] = loads(d.get("rejected_by_filter"), {})
    d["notes"] = loads(d.get("notes"), [])
    d["progress"] = loads(d.get("progress"), {})
    d["source_health"] = loads(d.get("source_health"), [])
    d["rejects"] = loads(d.get("rejects"), [])
    d["usd_by_stage"] = loads(d.get("usd_by_stage"), {})
    d["log_tail"] = loads(d.get("log_tail"), [])
    d["programs_snapshot"] = loads(d.get("programs_snapshot"), [])
    d["funder_groups"] = loads(d.get("funder_groups"), [])
    return d


def get_run(conn, run_id: str, *, org_id: str | None = None) -> dict | None:
    """One run. `org_id=None` is a deliberate escape hatch for the two callers that
    legitimately have a run id but no org context — `RunManager._finalize`, which is
    closing out a process it launched itself, and the boot-time reconciler. Every
    request-driven caller passes one."""
    if org_id is None:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM runs WHERE id=? AND org_id=?",
                           (run_id, org_id)).fetchone()
    return _run_out(row) if row else None


def latest_run(conn, *, org_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM runs WHERE org_id=? ORDER BY started_at DESC LIMIT 1",
        (org_id,)).fetchone()
    return _run_out(row) if row else None


def list_runs(conn, limit: int = 20, *, org_id: str) -> list[dict]:
    return [_run_out(r) for r in conn.execute(
        "SELECT * FROM runs WHERE org_id=? ORDER BY started_at DESC LIMIT ?",
        (org_id, limit))]


def list_runs_for_month(conn, *, org_id: str, month: str) -> list[dict]:
    """One card per search that ran in this month, newest first — what Past findings
    shows instead of one pooled list. Excludes the reject rows and the technical log
    (hundreds of rows nobody reads from this view; `GET /api/runs/{id}/rejects` and the
    stage boxes already own that) and excludes runs still in progress — a run belongs
    here once it has something to report.

    Also excludes a run that never actually read anything: `sources_attempted == 0`
    means the crawl never started — the kill switch was off, there was no key, or no
    funder was ticked, all refused before `agent.run.crawl()` ever ran. That is not a
    search with a quiet result; it is not a search. A real search that tried and found
    nothing (`sources_attempted > 0`, zero kept) still belongs here — CLAUDE.md's own
    point is that a low count is not a failure, only an empty attempt is not an
    attempt.

    `kept_count` is **not** `opportunities_scored` off the run row — that is how many
    this run scored the day it ran, and does not shrink when a later search re-confirms
    the same finding and takes over its `run_id` (the same dedup rule every other
    findings view already follows). It is a live count against `opportunities` so an
    old search's card always says how many of its findings are still being shown, not
    how many it originally produced.
    """
    rows = conn.execute(
        "SELECT * FROM runs WHERE org_id=? AND status<>'running' AND sources_attempted>0 "
        "AND substr(started_at, 1, 7)=? ORDER BY started_at DESC",
        (org_id, month),
    ).fetchall()
    out = []
    for r in rows:
        d = {k: v for k, v in _run_out(r).items() if k not in ("rejects", "log_tail")}
        d["kept_count"] = conn.execute(
            "SELECT COUNT(*) AS n FROM opportunities WHERE org_id=? AND run_id=?",
            (org_id, d["id"])).fetchone()["n"]
        out.append(d)
    return out


def spend_summary(conn, *, org_id: str, month: str | None = None) -> dict:
    """What this org has spent through Fundworthy this calendar month.

    Deliberately *our* number, summed from the run log, rather than a reading of the
    org's Anthropic balance — Anthropic publishes no credit-balance endpoint or header.
    (`anthropic-ratelimit-tokens-remaining` looks like one and is not: it is tokens per
    minute, and it refills.) So the honest thing to show a nonprofit is what this app
    spent of their money, which is the number they can actually hold us to.
    """
    key = month or month_key()
    row = conn.execute(
        "SELECT COALESCE(SUM(usd_spent), 0.0) AS spent, COUNT(*) AS runs "
        "FROM runs WHERE org_id=? AND started_at >= ?",
        (org_id, f"{key}-01"),
    ).fetchone()

    settings = get_settings(conn, org_id=org_id)
    cap = float(settings["monthly_budget_usd"])
    spent = round(float(row["spent"]), 4)
    return {
        "month": key,
        "spent_usd": spent,
        "cap_usd": cap,
        "remaining_usd": round(max(0.0, cap - spent), 4),
        "runs": row["runs"],
        "over_cap": spent >= cap,
    }


def runs_today(conn, *, org_id: str) -> int:
    """How many searches this org has started in the last 24 hours.

    The monthly spend cap bounds money, which only bites an org that has supplied a key.
    An org with no key still costs us: the free deterministic tier fetches real pages
    from real funders' websites, from one server IP. With open sign-up that is the abuse
    surface that money no longer covers.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE org_id=? AND started_at >= ?",
        (org_id, since),
    ).fetchone()["n"]


def platform_stats(conn) -> dict:
    """How the whole install is doing. **Crosses every tenant boundary in this file.**

    Everything else here takes an `org_id` and refuses to work without one. This does the
    opposite on purpose, which is why it is the only function with a warning on it and
    why `app/main.py` puts it behind a separate admin gate rather than the ordinary
    sign-in.

    It counts and it aggregates. No org names, no email addresses, no funder lists, no
    findings — the question is "is the product working", and none of those answer it.
    Add a field here only if you can say which decision it changes.
    """
    def one(sql, params=()):
        return conn.execute(sql, params).fetchone()

    since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    orgs = one("SELECT COUNT(*) AS n FROM orgs")["n"]
    users = one("SELECT COUNT(*) AS n FROM users")["n"]
    active_7d = one("SELECT COUNT(DISTINCT org_id) AS n FROM users WHERE last_seen_at >= ?",
                    (since_7d,))["n"]

    # The number that says whether this is a product or a demo: orgs that supplied their
    # own key. Everything before that is somebody looking; this is somebody committing.
    with_key = one(
        "SELECT COUNT(*) AS n FROM settings WHERE key=? AND value IS NOT NULL",
        (API_KEY_SETTING,))["n"]

    runs = one("SELECT COUNT(*) AS n, COALESCE(SUM(usd_spent), 0) AS spent FROM runs "
               "WHERE started_at >= ?", (since_30d,))
    by_status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM runs WHERE started_at >= ? GROUP BY status",
        (since_30d,))}

    findings = one("SELECT COUNT(*) AS n FROM opportunities WHERE month_key = ?",
                   (month_key(),))["n"]
    # Findings the accuracy gate could not verify. A rising share here is the product
    # getting less trustworthy, and it is invisible from any single org's dashboard.
    unverified = one("SELECT COUNT(*) AS n FROM opportunities "
                     "WHERE month_key = ? AND needs_human_check = 1",
                     (month_key(),))["n"]

    return {
        "orgs": orgs,
        "users": users,
        "orgs_active_7d": active_7d,
        "orgs_with_own_key": with_key,
        "runs_30d": runs["n"],
        "runs_by_status_30d": by_status,
        "spend_30d_usd": round(float(runs["spent"]), 4),
        "findings_this_month": findings,
        "findings_needing_check": unverified,
        "month": month_key(),
    }


def reconcile_interrupted_runs(conn) -> int:
    """Close out rows left at 'running' by a process that is no longer alive.

    Run state lives in `RunManager`, which is per-process memory. A `systemctl restart`
    — the last step of every deploy — takes the API down together with any pipeline
    subprocess it had launched, and nothing is left to write the row back. The run then
    reads as permanently in-progress: the dashboard shows a spinner for a search that
    stopped days ago.

    Called once at startup, before serving. Deliberately unscoped by org — a restart
    interrupts every org's work at once, and at boot there is no user to attribute it to.
    """
    cur = conn.execute(
        "UPDATE runs SET status='failed', stop_reason='interrupted_by_restart', "
        "finished_at=?, progress=? WHERE status='running'",
        (now_iso(), dumps({"phase": "failed",
                           "message": "The server restarted while this search was "
                                      "running, so it did not finish."})),
    )
    if cur.rowcount:
        log.warning("marked %d interrupted run(s) as failed at startup", cur.rowcount)
    return cur.rowcount


# --- misc ---------------------------------------------------------------------

def _nullable_int(value) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# --- funders other nonprofits have shared ---------------------------------------
#
# The pool is every hand-added funder belonging to an org that has ticked "share the
# funders I add", minus anything reported, minus anything whose page did not load.
#
# Deduplicated on the web address, because two nonprofits adding the same foundation is
# the common case and the expected one — and the count of how many added it is the only
# trust signal here that comes from people rather than from a fetch. It is shown ("added
# by 3 nonprofits") and no org is ever named: who funds whom is exactly the kind of thing
# a small nonprofit sector gossips about, and this feature is not here to leak it.

def shared_funders(conn, *, org_id: str, limit: int = 60) -> list[dict]:
    """Funders other orgs are offering, that this org does not already have.

    `org_id` is excluded from the results rather than filtered afterwards: seeing your
    own additions listed back to you as somebody else's suggestion is confusing, and
    "add" would be a no-op.
    """
    mine = {(r["url"] or "").strip().rstrip("/").casefold()
            for r in conn.execute("SELECT url FROM funders WHERE org_id=?", (org_id,))}
    # Blocking means "stop suggesting this", so it has to reach the one screen whose
    # whole job is suggesting things. Matched on name as well as URL, because another
    # org may well have typed the same funder with a different address.
    blocked = blocked_funder_keys(conn, org_id=org_id)

    rows = conn.execute(
        """SELECT f.id, f.org_id, f.name, f.url, f.sector, f.funder_type, f.notes,
                  f.check_note, f.checked_at
           FROM funders f
           JOIN settings s
             ON s.org_id = f.org_id AND s.key = 'share_funders' AND s.value = '1'
           WHERE f.added_by = 'user'
             AND f.org_id <> ?
             AND f.url IS NOT NULL AND f.url <> ''
             AND f.check_ok = 1
             AND NOT EXISTS (
                   SELECT 1 FROM funder_reports r
                   WHERE r.funder_org = f.org_id AND r.funder_id = f.id
                     AND r.status IN ('open', 'upheld'))
           ORDER BY f.name COLLATE NOCASE""",
        (org_id,))

    out: dict[str, dict] = {}
    for r in rows:
        key = (r["url"] or "").strip().rstrip("/").casefold()
        if key in mine or key in blocked:
            continue
        if str(r["name"] or "").strip().casefold() in blocked:
            continue
        if key in out:
            out[key]["added_by_count"] += 1
            continue
        out[key] = {
            "id": r["id"], "from_org": r["org_id"],
            "name": r["name"], "url": r["url"], "sector": r["sector"],
            "funder_type": r["funder_type"], "notes": (r["notes"] or "")[:280],
            # Evidence, verbatim, with the date it was true. Never a badge.
            "evidence": r["check_note"], "checked_at": r["checked_at"],
            "added_by_count": 1,
        }
        if len(out) >= limit:
            break
    return list(out.values())


def report_shared_funder(conn, *, funder_org: str, funder_id: str,
                         reported_by: str, reason: str) -> dict:
    """Object to a shared funder. Hides it from the pool at once, pending review.

    Idempotent per reporting org, so a double-click does not stack two reports against
    the same entry and make one objection look like a pattern.
    """
    import hashlib

    from .db import now_iso

    existing = conn.execute(
        "SELECT id FROM funder_reports WHERE funder_org=? AND funder_id=? "
        "AND reported_by=? AND status='open'",
        (funder_org, funder_id, reported_by)).fetchone()
    if existing:
        return {"report_id": existing["id"], "already": True}

    rid = hashlib.sha256(
        f"{funder_org}:{funder_id}:{reported_by}:{now_iso()}".encode()).hexdigest()[:16]
    conn.execute(
        "INSERT INTO funder_reports(id, funder_org, funder_id, reported_by, reason, "
        "created_at, status) VALUES(?,?,?,?,?,?,'open')",
        (rid, funder_org, funder_id, reported_by, reason.strip()[:500], now_iso()))
    return {"report_id": rid, "already": False}


def all_reports(conn) -> list[dict]:
    """The moderation queue, for an install admin — one card per FUNDER, not one per
    report. Crosses every tenant boundary, so the route that calls this is gated by
    `FUNDWORTHY_ADMIN_EMAILS` and nothing else.

    Two or more nonprofits can independently report the same shared funder, which used
    to surface as separate rows — "reported by 3 organizations" read as three unrelated
    entries, and resolving one of them left the funder hidden-but-unresolved against the
    other two (see `resolve_report_group`, which this grouping makes correct). Includes
    every status, not only 'open': the queue also has to show what was already decided,
    for "taken down" / "left up" counts on the tab.
    """
    rows = conn.execute(
        """SELECT r.funder_org, r.funder_id, r.reason, r.created_at, r.status,
                  r.reported_by, f.name, f.url, f.sector
           FROM funder_reports r
           LEFT JOIN funders f ON f.org_id = r.funder_org AND f.id = r.funder_id
           ORDER BY r.created_at""")
    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["funder_org"], r["funder_id"])
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "funder_org": r["funder_org"], "funder_id": r["funder_id"],
                "name": r["name"], "url": r["url"], "sector": r["sector"],
                "reason": r["reason"], "created_at": r["created_at"],
                "reported_by": set(), "status": r["status"],
            }
        g["reported_by"].add(r["reported_by"])
        # The most recent reason and date win — that is the one a reviewer should read.
        if r["created_at"] >= g["created_at"]:
            g["reason"], g["created_at"] = r["reason"], r["created_at"]
        # 'open' if anything about this funder still needs a decision; otherwise
        # whatever the (normally unanimous) resolved rows agree on.
        if g["status"] != "open" and r["status"] == "open":
            g["status"] = "open"
    out = []
    for g in groups.values():
        count = len(g.pop("reported_by"))
        out.append({**g, "reported_by_count": count})
    out.sort(key=lambda g: g["created_at"], reverse=True)
    return out


def resolve_report_group(conn, funder_org: str, funder_id: str, *,
                         uphold: bool, by: str) -> int:
    """Take a funder down for good, or dismiss every OPEN report against it and put it
    back in the pool. Resolves every open row for this funder at once, not just one —
    a funder several nonprofits independently objected to is one decision, and
    dismissing only one of several open rows used to leave the others still hiding it
    (the shared-funders query excludes on ANY row with status in open/upheld). Returns
    how many rows were actually resolved, so the caller can tell "nothing to do" from
    "done"."""
    from .db import now_iso

    cur = conn.execute(
        "UPDATE funder_reports SET status=?, resolved_at=?, resolved_by=? "
        "WHERE funder_org=? AND funder_id=? AND status='open'",
        ("upheld" if uphold else "dismissed", now_iso(), by, funder_org, funder_id))
    return cur.rowcount


# --- bug reports ----------------------------------------------------------------
#
# Recorded BEFORE the app ever tries to file them on GitHub — see app/bugreport.py —
# so a report is never lost even when GitHub is unreachable or the install has no
# token configured. github_issue_url/number stay NULL and error carries the reason.

def create_bug_report(conn, *, org_id: str, title: str, description: str, page: str,
                      reported_by: str) -> str:
    stamp = now_iso()
    report_id = hashlib.sha256(
        f"{org_id}:{title}:{reported_by}:{stamp}".encode()).hexdigest()[:16]
    conn.execute(
        "INSERT INTO bug_reports(id, org_id, title, description, page, reported_by, "
        "created_at) VALUES(?,?,?,?,?,?,?)",
        (report_id, org_id, title, description, page, reported_by, stamp))
    return report_id


def record_bug_report_result(conn, report_id: str, *, issue_url: str | None = None,
                             issue_number: int | None = None, error: str = "") -> None:
    conn.execute(
        "UPDATE bug_reports SET github_issue_url=?, github_issue_number=?, error=? "
        "WHERE id=?",
        (issue_url, issue_number, error, report_id))


def count_recent_bug_reports(conn, *, org_id: str) -> int:
    """How many bug reports this org has filed in the last 24 hours — a genuine
    rolling window, not a UTC-calendar-day count. It used to be the latter
    (`created_at >= today's date`), which let an org file a full batch just before UTC
    midnight and a second full batch just after — up to 2x the advertised cap within
    minutes, while the 429 message it backs has always promised "the last 24 hours."
    `created_at` is ISO8601 (`now_iso()`), so a plain string comparison against an
    ISO8601 cutoff is still a correct >= without parsing every row."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) AS n FROM bug_reports WHERE org_id=? AND created_at >= ?",
        (org_id, since)).fetchone()["n"]
