"""Static JSON sink for the website. (CLAUDE.md §4; decision A6 Opt 2)

Writes ONE committed file the read-only site loads directly — no serverless reader, no
Google credential in a browser, and the Sheet stays private. The website renders these
opportunities for Mauri to review and prune; the ones she keeps get exported to her own
Google Sheet via her Gmail later (Phase 3). This sink only produces the data file.

Only public-safe fields are emitted (an explicit allowlist). Any award or deadline that
did not survive the accuracy gate (agent/verify.py) is already null on the record, so
the page can never display an unsourced number — even to a funder reading over a
shoulder.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.models import Opportunity, RunLog

from .base import split_sections

# Fields safe to publish. Kept explicit so any future Opportunity field is opt-in here,
# never leaked by default. (Opportunity carries no internal Funders-tab data today.)
PUBLIC_FIELDS = (
    "id", "title", "funder", "award_min", "award_max", "award_typical", "deadline",
    "deadline_type", "estimated_effort_hours", "program_match", "score",
    "score_rationale", "funder_type", "service_areas", "geography",
    "form_990_available", "confidence_pct", "contact_note",
    "source_url", "verified", "needs_human_check", "found_on", "section",
    "source_kind", "application_lead_time_days", "time_to_funds_days",
    "ein", "form_990_url", "form_990_year",
    "form_990_total_revenue", "form_990_total_expenses",
)


def _public(opp: Opportunity) -> dict:
    d = opp.to_dict()
    row = {k: d[k] for k in PUBLIC_FIELDS}
    row["days_left"] = opp.days_until_deadline
    return row


class WebJsonSink:
    """Emits dashboard/public/run.json: run stats + the ranked and unscored lists."""

    name = "web"

    def __init__(self, out_path: str | Path = "dashboard/public/run.json") -> None:
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._opportunities: list[Opportunity] = []

    def write_opportunities(self, opportunities: list[Opportunity],
                            run: RunLog | None = None) -> int:
        # Held until write_run_log so the whole page is one atomic file write.
        self._opportunities = list(opportunities)
        return len(opportunities)

    def write_run_log(self, run: RunLog) -> None:
        rows = self._month_rows()
        if rows is None:
            scored, not_stated = split_sections(self._opportunities)
            rows = {"scored": [_public(o) for o in scored],
                    "amount_not_stated": [_public(o) for o in not_stated]}

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": run.to_dict(),
            **rows,
        }
        self.out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _month_rows(self) -> dict | None:
        """The month's findings from the archive, or None if there is no database.

        This file is read as *the brief*, not as a run artifact, and those differ the
        moment monthly dedup exists: a re-run mid-week legitimately finds nothing new,
        and writing only that run's output would blank a page that should still be
        showing everything found so far this month. The run block above still reports
        the run itself, so "this run found nothing new" stays visible without the
        results disappearing underneath it.
        """
        try:
            from app.db import db_path, session
            from app.repo import list_opportunities

            if not db_path().exists():
                return None
            with session() as conn:
                rows = list_opportunities(conn)
        except Exception:  # noqa: BLE001 — no database is a normal state
            return None

        allowed = set(PUBLIC_FIELDS) | {"days_left"}
        public = [{k: v for k, v in r.items() if k in allowed} for r in rows]
        return {
            "scored": [r for r in public if r.get("section") == "scored"],
            "amount_not_stated": [r for r in public if r.get("section") != "scored"],
        }
