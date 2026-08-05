"""The monthly archive: dedup on the way in, purge on the way out.

The problem this solves is the user's, not the database's. If the agent runs every week
and the same San Diego Foundation page is open all month, they see the same row four
Thursdays running and start skimming past the whole list. So: a finding is shown once
per month, and the month resets.

Two operations, both cheap:

`seen_this_month`  — a primary-key probe against `opportunities`. Runs inside the free
                     deterministic tier, before triage, so a repeat costs $0.00 rather
                     than a Haiku call. With `id` as a TEXT PRIMARY KEY the lookup is an
                     index probe: constant time whether the month holds 20 rows or 2,000.

`purge_old_months`  — `DELETE FROM opportunities WHERE month_key < <this month>`, run once
                     at the start of each run. Bounds the file, and lets a grant seen in
                     July legitimately resurface in August. That resurfacing is the
                     intended, documented exception (CLAUDE.md) — the archive is a
                     "don't repeat yourself this month" index, not a permanent record.

Nothing here decides *what* to keep; it only decides what the user has already been shown.
"""

from __future__ import annotations

import logging

from .db import month_key

log = logging.getLogger(__name__)


def seen_this_month(conn, opportunity_id: str, *, org_id: str,
                    month: str | None = None) -> bool:
    """Has this exact finding already been surfaced in the current month?"""
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE id=? AND month_key=? AND org_id=? LIMIT 1",
        (opportunity_id, month or month_key(), org_id),
    ).fetchone()
    return row is not None


def seen_ids_this_month(conn, *, org_id: str, month: str | None = None) -> set[str]:
    """Every id already shown this month **to this org**, as one set.

    A crawl checks hundreds of candidates. Reading the month's ids once and probing a
    Python set beats hundreds of round trips to SQLite, and the month's row count is
    bounded by the purge, so the set stays small by construction.

    The org predicate is not cosmetic. Opportunity ids are `stable_id(source_url, title)`,
    so the same grant page produces the same id for everybody. Unscoped, the second org to
    run in a month inherited the first org's dedup set and never saw a single grant the
    first org had already found — dropped in the free tier, never fetched, never scored,
    with nothing in the run log to explain the empty result.
    """
    return {
        r["id"] for r in conn.execute(
            "SELECT id FROM opportunities WHERE month_key=? AND org_id=?",
            (month or month_key(), org_id),
        )
    }


def purge_old_months(conn, *, org_id: str, keep: str | None = None) -> int:
    """Delete every row from a month before `keep` (default: the current month).

    Returns how many rows went, so the run log can say it out loud. A purge that
    happens silently is indistinguishable from data loss.

    Scoped to one org, and that scoping is the whole point: this runs at the start of
    every run, before any fetching. Unscoped it meant any org pressing Re-run on the 1st
    of the month wiped every other org's archive first.
    """
    keep = keep or month_key()
    cur = conn.execute(
        "DELETE FROM opportunities WHERE month_key < ? AND org_id=?", (keep, org_id))
    removed = cur.rowcount or 0
    if removed:
        log.info("archive: purged %d row(s) from before %s for org %s",
                 removed, keep, org_id)
    return removed


def month_summary(conn, *, org_id: str) -> dict:
    """Counts for the Archived findings page."""
    rows = conn.execute(
        """SELECT month_key,
                  COUNT(*)                                        AS total,
                  SUM(CASE WHEN section='scored' THEN 1 ELSE 0 END) AS scored,
                  SUM(needs_human_check)                          AS needs_check
             FROM opportunities
            WHERE org_id=?
            GROUP BY month_key
            ORDER BY month_key DESC""",
        (org_id,),
    ).fetchall()
    return {
        "current_month": month_key(),
        "months": [dict(r) for r in rows],
    }
