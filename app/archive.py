"""The monthly archive: dedup on the way in, purge on the way out.

The problem the dedup half solves is the user's, not the database's. If the agent runs
every week and the same San Diego Foundation page is open all month, they see the same
row four Thursdays running and start skimming past the whole list. So: a finding is
shown once per month, and the month resets — a grant seen in July can legitimately
resurface as a fresh row in August, which is the intended, documented exception
(CLAUDE.md), not a bug in the dedup.

Two operations, both cheap:

`seen_this_month`  — a primary-key probe against `opportunities`, scoped to the CURRENT
                     month only, regardless of the retention window below. Runs inside
                     the free deterministic tier, before triage, so a repeat costs $0.00
                     rather than a Haiku call.

`purge_old_months`  — `DELETE FROM opportunities WHERE month_key < <12 months back>`,
                     run once at the start of each run. Bounds the file without erasing
                     Past findings: a search from ten months ago is still a real record
                     of what ran and what it cost, and CLAUDE.md's dedup exception only
                     needs the CURRENT month's ids, not the whole table swept every
                     month — the two used to share one threshold, which is why the
                     archive only ever held one month at a time.

Nothing here decides *what* to keep; it only decides what the user has already been shown
and how long a record survives.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .db import month_key

log = logging.getLogger(__name__)

# "The whole year", in calendar months, including the current one — Past findings'
# own header says "anything older than twelve months is removed", so this is the one
# number that promise actually has to match.
RETENTION_MONTHS = 12


def _months_before(n: int, *, now: datetime | None = None) -> str:
    """The `month_key` exactly `n` calendar months before now, wrapping year
    boundaries correctly (unlike naive `month - n` arithmetic, which goes negative
    every January)."""
    now = now or datetime.now(timezone.utc)
    total = now.year * 12 + (now.month - 1) - n
    year, zero_based_month = divmod(total, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


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
    """Delete every row from a month before `keep` (default: `RETENTION_MONTHS` back
    from the current month — a rolling year of Past findings, current month included).

    Returns how many rows went, so the run log can say it out loud. A purge that
    happens silently is indistinguishable from data loss.

    Scoped to one org, and that scoping is the whole point: this runs at the start of
    every run, before any fetching. Unscoped it meant any org pressing Re-run on the 1st
    of the month wiped every other org's archive first.
    """
    keep = keep or _months_before(RETENTION_MONTHS - 1)
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
