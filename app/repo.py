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
from datetime import date, datetime, timezone
from typing import Any

from .db import (DEFAULT_SETTINGS, dumps, loads, month_key, now_iso)
from .secrets import SETTING_NAME as API_KEY_SETTING

log = logging.getLogger(__name__)

# Settings the browser is allowed to read and write. The API key is deliberately not in
# this set — it has its own write-only path in app/secrets.py.
PUBLIC_SETTINGS = tuple(DEFAULT_SETTINGS.keys())

_INT_SETTINGS = {"min_award", "min_deadline_runway_days", "max_opportunities"}
_FLOAT_SETTINGS = {"run_budget_usd"}
_BOOL_SETTINGS = {"enabled", "search_beyond_partners"}
_JSON_SETTINGS = {"sectors_active"}


# --- settings -----------------------------------------------------------------

def get_settings(conn) -> dict[str, Any]:
    """Typed settings, with defaults filled in for anything missing."""
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
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


def update_settings(conn, changes: dict[str, Any]) -> dict[str, Any]:
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
            "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, stored, stamp),
        )
    return get_settings(conn)


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


def list_programs(conn, *, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM programs"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY active DESC, name"
    return [_program_out(r) for r in conn.execute(sql)]


def get_program(conn, program_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM programs WHERE id=?", (program_id,)).fetchone()
    return _program_out(row) if row else None


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()
    return slug[:40] or "PROGRAM"


def create_program(conn, data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("a program needs a name")

    slug = str(data.get("slug") or slugify(name))
    # Two cards called "RISE Arts" is a data bug that only shows up weeks later as a
    # program silently not being searched. Disambiguate at write time instead.
    existing = {r["slug"] for r in conn.execute("SELECT slug FROM programs")}
    base, n = slug, 2
    while slug in existing:
        slug, n = f"{base}_{n}", n + 1

    program_id = uuid.uuid4().hex[:16]
    stamp = now_iso()
    conn.execute(
        """INSERT INTO programs(
               id, name, slug, summary, what_it_funds, keywords, funder_types,
               search_queries, min_award, active, source_url, drafted_by_ai,
               reviewed_by_human, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            program_id, name, slug,
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
    return get_program(conn, program_id)  # type: ignore[return-value]


def update_program(conn, program_id: str, changes: dict) -> dict | None:
    if get_program(conn, program_id) is None:
        return None
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
        values.extend([now_iso(), program_id])
        conn.execute(f"UPDATE programs SET {', '.join(sets)} WHERE id=?", values)
    return get_program(conn, program_id)


def delete_program(conn, program_id: str) -> bool:
    cur = conn.execute("DELETE FROM programs WHERE id=?", (program_id,))
    return cur.rowcount > 0


# --- funders ------------------------------------------------------------------

_FUNDER_FIELDS = ("name", "url", "sector", "funder_type", "warm", "active",
                  "tier", "confidence", "programs", "notes", "exclude_reason")


def _funder_out(row) -> dict:
    d = dict(row)
    d["programs"] = loads(d.get("programs"), [])
    d["warm"] = bool(d.get("warm"))
    d["active"] = bool(d.get("active"))
    return d


def list_funders(conn, *, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM funders"
    if active_only:
        sql += " WHERE active=1"
    # Alphabetical, case-insensitively. It used to be `warm DESC, name` — partners
    # first — which is exactly the priority the stakeholder asked us to drop. NOCASE
    # because SQLite's default is byte order, which puts every capitalised name above
    # every lowercase one and reads as unsorted to a person.
    sql += " ORDER BY name COLLATE NOCASE"
    return [_funder_out(r) for r in conn.execute(sql)]


_F990 = ("ein", "form_990_url", "form_990_year",
         "form_990_total_revenue", "form_990_total_expenses")


def funder_990_map(conn) -> dict[str, dict]:
    """{casefolded funder name: 990 facts} for everything already looked up.

    Read once per run and matched in memory. Funder financials change annually, so
    re-querying an external API every week for data that moves once a year would be
    exactly the kind of fragile, pointless dependency the stakeholder asked us to avoid.
    """
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT name, ein, form_990_url, form_990_year, form_990_total_revenue, "
        "form_990_total_expenses FROM funders WHERE ein IS NOT NULL"
    ):
        out[str(r["name"]).strip().casefold()] = {k: r[k] for k in _F990}
    return out


def save_funder_990(conn, funder_id: str, data: dict | None) -> None:
    """Cache a lookup result. A miss is cached too — as a checked_at with no EIN — so
    we do not re-ask an API every week about a funder that has no filing (every
    government body and tribal nation in the registry)."""
    data = data or {}
    conn.execute(
        "UPDATE funders SET ein=?, form_990_url=?, form_990_year=?, "
        "form_990_total_revenue=?, form_990_total_expenses=?, form_990_checked_at=? "
        "WHERE id=?",
        (data.get("ein"), data.get("form_990_url"), data.get("form_990_year"),
         data.get("form_990_total_revenue"), data.get("form_990_total_expenses"),
         now_iso(), funder_id),
    )


def funders_needing_990(conn) -> list[dict]:
    return [_funder_out(r) for r in conn.execute(
        "SELECT * FROM funders WHERE form_990_checked_at IS NULL AND active=1")]


def excluded_funder_names(conn) -> set[str]:
    """Funders on the remove list, casefolded, for result-level filtering.

    Skipping them at the crawl is the cheap half and catches most of it. But the two
    indexed databases return grants from every funder in the state, so an excluded
    funder can still arrive through Grants.gov or the CA portal — which would put
    exactly the opportunity they said they do not want back on their list, by a different
    door. Both doors have to be closed.
    """
    return {
        str(r["name"]).strip().casefold()
        for r in conn.execute("SELECT name FROM funders WHERE active=0")
    }


def get_funder(conn, funder_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM funders WHERE id=?", (funder_id,)).fetchone()
    return _funder_out(row) if row else None


def create_funder(conn, data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("a funder needs a name")
    funder_id = hashlib.sha256(name.casefold().encode()).hexdigest()[:16]
    stamp = now_iso()
    conn.execute(
        """INSERT INTO funders(
               id, name, url, sector, funder_type, warm, active, tier, confidence,
               programs, notes, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               url=excluded.url, sector=excluded.sector,
               funder_type=excluded.funder_type, warm=excluded.warm,
               active=excluded.active, programs=excluded.programs,
               notes=excluded.notes, updated_at=excluded.updated_at""",
        (
            funder_id, name, data.get("url"),
            str(data.get("sector", "other")), str(data.get("funder_type", "other")),
            1 if data.get("warm") else 0,
            0 if data.get("active") is False else 1,
            int(data.get("tier", 1) or 1), int(data.get("confidence", 1) or 1),
            dumps(data.get("programs") or []), str(data.get("notes", "")),
            stamp, stamp,
        ),
    )
    return get_funder(conn, funder_id)  # type: ignore[return-value]


def update_funder(conn, funder_id: str, changes: dict) -> dict | None:
    if get_funder(conn, funder_id) is None:
        return None
    sets, values = [], []
    for field in _FUNDER_FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field == "programs":
            value = dumps(value if isinstance(value, list) else [])
        elif field in {"warm", "active"}:
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
        sets.append("updated_at=?")
        values.extend([now_iso(), funder_id])
        conn.execute(f"UPDATE funders SET {', '.join(sets)} WHERE id=?", values)
    return get_funder(conn, funder_id)


def delete_funder(conn, funder_id: str) -> bool:
    cur = conn.execute("DELETE FROM funders WHERE id=?", (funder_id,))
    return cur.rowcount > 0


# --- opportunities ------------------------------------------------------------

_OPP_JSON = {"program_match", "service_areas"}


def _opp_out(row) -> dict:
    d = dict(row)
    for f in _OPP_JSON:
        d[f] = loads(d.get(f), [])
    d["verified"] = bool(d.get("verified"))
    d["needs_human_check"] = bool(d.get("needs_human_check"))
    if d.get("form_990_available") is not None:
        d["form_990_available"] = bool(d["form_990_available"])
    d["days_left"] = _days_left(d.get("deadline"))
    return d


def _days_left(deadline: str | None) -> int | None:
    if not deadline:
        return None
    try:
        return (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return None


def save_opportunity(conn, opp, run_id: str | None = None) -> None:
    """Upsert one Opportunity. Re-running the same week updates rather than duplicates."""
    d = opp.to_dict()
    stamp = now_iso()
    conn.execute(
        """INSERT INTO opportunities(
               id, run_id, month_key, found_on, title, funder, source_url,
               award_min, award_max, award_typical, deadline, deadline_type,
               estimated_effort_hours, program_match, score, score_rationale,
               funder_type, service_areas, geography, form_990_available,
               confidence_pct, contact_note, verified, needs_human_check,
               section, source_kind, application_lead_time_days, time_to_funds_days,
               ein, form_990_url, form_990_year, form_990_total_revenue,
               form_990_total_expenses, fetched_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               run_id=excluded.run_id, score=excluded.score,
               score_rationale=excluded.score_rationale,
               award_min=excluded.award_min, award_max=excluded.award_max,
               award_typical=excluded.award_typical, deadline=excluded.deadline,
               deadline_type=excluded.deadline_type,
               estimated_effort_hours=excluded.estimated_effort_hours,
               program_match=excluded.program_match,
               funder_type=excluded.funder_type,
               service_areas=excluded.service_areas, geography=excluded.geography,
               form_990_available=excluded.form_990_available,
               confidence_pct=excluded.confidence_pct,
               contact_note=excluded.contact_note, verified=excluded.verified,
               needs_human_check=excluded.needs_human_check,
               section=excluded.section, source_kind=excluded.source_kind,
               application_lead_time_days=excluded.application_lead_time_days,
               time_to_funds_days=excluded.time_to_funds_days,
               ein=excluded.ein, form_990_url=excluded.form_990_url,
               form_990_year=excluded.form_990_year,
               form_990_total_revenue=excluded.form_990_total_revenue,
               form_990_total_expenses=excluded.form_990_total_expenses,
               fetched_at=excluded.fetched_at""",
        (
            d["id"], run_id, month_key(), d.get("found_on") or stamp[:10],
            d["title"], d["funder"], d["source_url"],
            d["award_min"], d["award_max"], d.get("award_typical"),
            d["deadline"], d.get("deadline_type", "unknown"),
            d["estimated_effort_hours"], dumps(d["program_match"]),
            d["score"], d["score_rationale"],
            d.get("funder_type", "unknown"), dumps(d.get("service_areas") or []),
            d.get("geography"),
            None if d.get("form_990_available") is None else int(d["form_990_available"]),
            d.get("confidence_pct"), d.get("contact_note"),
            int(d["verified"]), int(d["needs_human_check"]),
            d["section"], d.get("source_kind", "funder_page"),
            d.get("application_lead_time_days"), d.get("time_to_funds_days"),
            d.get("ein"), d.get("form_990_url"), d.get("form_990_year"),
            d.get("form_990_total_revenue"), d.get("form_990_total_expenses"),
            d["fetched_at"],
        ),
    )


def list_opportunities(conn, *, month: str | None = None,
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
    where, params = [], []
    if month:
        where.append("month_key=?")
        params.append(month)
    if run_id:
        where.append("run_id=?")
        params.append(run_id)
    sql = "SELECT * FROM opportunities"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY needs_human_check ASC, score DESC, funder ASC"
    return [_opp_out(r) for r in conn.execute(sql, params)]


def available_months(conn) -> list[str]:
    return [r["month_key"] for r in conn.execute(
        "SELECT DISTINCT month_key FROM opportunities ORDER BY month_key DESC")]


# --- runs ---------------------------------------------------------------------

def create_run(conn, run_id: str | None = None) -> str:
    run_id = run_id or uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO runs(id, started_at, status) VALUES(?,?, 'running')",
        (run_id, now_iso()),
    )
    return run_id


def update_run(conn, run_id: str, **fields) -> None:
    if not fields:
        return
    for json_field in ("rejected_by_filter", "notes", "progress", "source_health"):
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
    return d


def get_run(conn, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _run_out(row) if row else None


def latest_run(conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return _run_out(row) if row else None


def list_runs(conn, limit: int = 20) -> list[dict]:
    return [_run_out(r) for r in conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]


# --- misc ---------------------------------------------------------------------

def _nullable_int(value) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
