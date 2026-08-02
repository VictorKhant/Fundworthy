"""The monthly archive: dedup on the way in, purge on the way out.

The problem this solves is Mauri's, not the database's. If the agent runs every week
and the same San Diego Foundation page is open all month, she sees the same row four
Thursdays running and starts skimming past the whole list. So: a finding is shown once
per month, and the month resets.

Two operations, both cheap:

`seen_this_month`  — a primary-key probe against `opportunities`. Runs inside the free
                     deterministic tier, before triage, so a repeat costs $0.00 rather
                     than a Haiku call. With `id` as a TEXT PRIMARY KEY the lookup is an
                     index probe: constant time whether the month holds 20 rows or 2,000.

`purge_old_months`  — `DELETE FROM opportunities WHERE month_key < <this month>`, run once
                     at the start of each run. Bounds the file, and lets a grant seen in
                     July legitimately resurface in August. That resurfacing is the
                     intended, documented exception (docs/PLAN.md §2b) — the archive is a
                     "don't repeat yourself this month" index, not a permanent record.

Nothing here decides *what* to keep; it only decides what Mauri has already been shown.
"""

from __future__ import annotations

import logging

from .db import month_key

log = logging.getLogger(__name__)


def seen_this_month(conn, opportunity_id: str, *, month: str | None = None) -> bool:
    """Has this exact finding already been surfaced in the current month?"""
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE id=? AND month_key=? LIMIT 1",
        (opportunity_id, month or month_key()),
    ).fetchone()
    return row is not None


def seen_ids_this_month(conn, *, month: str | None = None) -> set[str]:
    """Every id already shown this month, as one set.

    A crawl checks hundreds of candidates. Reading the month's ids once and probing a
    Python set beats hundreds of round trips to SQLite, and the month's row count is
    bounded by the purge, so the set stays small by construction.
    """
    return {
        r["id"] for r in conn.execute(
            "SELECT id FROM opportunities WHERE month_key=?", (month or month_key(),)
        )
    }


def purge_old_months(conn, *, keep: str | None = None) -> int:
    """Delete every row from a month before `keep` (default: the current month).

    Returns how many rows went, so the run log can say it out loud. A purge that
    happens silently is indistinguishable from data loss.
    """
    keep = keep or month_key()
    cur = conn.execute("DELETE FROM opportunities WHERE month_key < ?", (keep,))
    removed = cur.rowcount or 0
    if removed:
        log.info("archive: purged %d row(s) from before %s", removed, keep)
    return removed


def month_summary(conn) -> dict:
    """Counts for the Archived findings page."""
    rows = conn.execute(
        """SELECT month_key,
                  COUNT(*)                                        AS total,
                  SUM(CASE WHEN section='scored' THEN 1 ELSE 0 END) AS scored,
                  SUM(needs_human_check)                          AS needs_check
             FROM opportunities
            GROUP BY month_key
            ORDER BY month_key DESC"""
    ).fetchall()
    return {
        "current_month": month_key(),
        "months": [dict(r) for r in rows],
    }
