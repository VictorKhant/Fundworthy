"""The Google Sheets sink — the product. (CLAUDE.md §4)

Mauri's whole surface area is this Sheet: she reads Opportunities, edits Config, and
turns the agent off from a cell. So the rendering rules matter as much as the data:

  - score_rationale sits in a column she can read without scrolling (§9).
  - Rows whose award amount was never stated go in their own block below the ranked
    list, clearly labeled, so they cannot be mistaken for scored results.
  - Records are keyed by id, so a re-run updates a row rather than duplicating it.
  - Nothing is ever deleted. If the agent is wrong, she still has the history.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from agent.models import Opportunity, RunLog

from .base import split_sections

log = logging.getLogger(__name__)

OPPORTUNITIES_TAB = "Opportunities"
RUNS_TAB = "Runs"

HEADERS = [
    "Score",
    "Why this one",          # score_rationale — kept early, she reads left to right
    "Funder",
    "Opportunity",
    "Award (low)",
    "Award (high)",
    "Deadline",
    "Days left",
    "Est. hours",
    "Programs",
    "Needs a human check",
    "Link",
    "Found on",
    "id",                    # last: bookkeeping, not for reading
]

RUN_HEADERS = [
    "When it ran", "Minutes", "Funders checked", "Couldn't reach",
    "Pages read", "Ruled out for free", "Brought to you", "Amount not stated",
    "Cost", "How it ended", "Notes",
]

# §9: no technical vocabulary on anything Mauri reads. StopReason values are for
# the log and the dashboard; this is what she sees.
STOP_REASON_PLAIN = {
    "target_met": "Found enough — stopped at the weekly limit",
    "budget": "Hit the spending limit for the week and stopped",
    "sources_exhausted": "Checked every funder on the list",
    "disabled": "You had turned it off (ENABLED was FALSE)",
    "error": "Something went wrong — see Notes",
}

SECTION_BANNER = (
    "AMOUNT NOT STATED ON THE FUNDER'S PAGE — these need a human look. "
    "They are not ranked, because there is no award amount to rank them by."
)


def _fmt_money(value: int | None) -> str:
    return f"${value:,}" if value is not None else ""


def _row(opp: Opportunity) -> list:
    days = opp.days_until_deadline
    return [
        opp.score if opp.award_max is not None else "",
        opp.score_rationale,
        opp.funder,
        opp.title,
        _fmt_money(opp.award_min),
        _fmt_money(opp.award_max),
        opp.deadline.isoformat() if opp.deadline else "not stated",
        days if days is not None else "",
        opp.estimated_effort_hours if opp.estimated_effort_hours is not None else "",
        ", ".join(p.value for p in opp.program_match),
        "YES" if opp.needs_human_check else "",
        opp.source_url,
        opp.fetched_at.strftime("%Y-%m-%d"),
        opp.id,
    ]


class SheetsSink:
    """Service-account write path. Mauri's only setup step is clicking Share (§4)."""

    name = "sheets"

    def __init__(self, sheet_id: str | None = None, credentials_path: str | None = None) -> None:
        self.sheet_id = sheet_id or os.environ.get("RISE_SHEET_ID")
        self.credentials_path = (
            credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
        if not self.sheet_id or not self.credentials_path:
            raise RuntimeError(
                "SheetsSink needs RISE_SHEET_ID and GOOGLE_APPLICATION_CREDENTIALS. "
                "Use --sink jsonl to run without credentials."
            )
        import gspread

        self._gc = gspread.service_account(filename=self.credentials_path)
        self._book = self._gc.open_by_key(self.sheet_id)

    def _tab(self, title: str, headers: list[str]):
        import gspread

        try:
            ws = self._book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._book.add_worksheet(title=title, rows=200, cols=max(len(headers), 14))
            ws.append_row(headers, value_input_option="USER_ENTERED")
            ws.freeze(rows=1)
        return ws

    def write_opportunities(self, opportunities: list[Opportunity]) -> int:
        scored, not_stated = split_sections(opportunities)
        ws = self._tab(OPPORTUNITIES_TAB, HEADERS)

        rows: list[list] = [_row(o) for o in scored]
        if not_stated:
            rows.append([""] * len(HEADERS))
            banner = [""] * len(HEADERS)
            banner[1] = SECTION_BANNER
            rows.append(banner)
            rows.extend(_row(o) for o in not_stated)

        if not rows:
            log.info("Nothing to write.")
            return 0

        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info("Wrote %d ranked + %d amount-not-stated rows.", len(scored), len(not_stated))
        return len(scored) + len(not_stated)

    def write_run_log(self, run: RunLog) -> None:
        """One row per run. This is how Mauri can tell the agent is still alive —
        and, when it isn't, roughly why, without calling anyone."""
        ws = self._tab(RUNS_TAB, RUN_HEADERS)
        d = run.to_dict()

        minutes = ""
        if run.finished_at:
            minutes = f"{(run.finished_at - run.started_at).total_seconds() / 60:.1f}"

        rejected_total = sum(d["rejected_by_filter"].values())
        rejects = ", ".join(f"{k.replace('_', ' ')}: {v}"
                            for k, v in sorted(d["rejected_by_filter"].items(),
                                               key=lambda kv: kv[1], reverse=True))
        notes = " | ".join(d["notes"])
        stop = STOP_REASON_PLAIN.get(d["stop_reason"] or "", d["stop_reason"] or "")

        ws.append_row(
            [
                run.started_at.strftime("%Y-%m-%d %H:%M UTC"),
                minutes,
                d["sources_attempted"],
                d["sources_failed"],
                d["candidates_parsed"],
                rejected_total,
                d["opportunities_scored"],
                d["opportunities_not_stated"],
                f"${d['usd_spent']:.2f}",
                stop,
                " || ".join(x for x in (rejects, notes) if x)[:4000],
            ],
            value_input_option="USER_ENTERED",
        )

    def ensure_config_tab(self) -> None:
        """Create the Config tab with plain-English labels if it is missing (§9).

        No technical vocabulary on this tab. Mauri has never seen a config file and
        should not be able to tell that this is one.
        """
        from agent.config import CONFIG_TAB, MIN_AWARD_PLACEHOLDER

        import gspread

        try:
            self._book.worksheet(CONFIG_TAB)
            return
        except gspread.WorksheetNotFound:
            pass

        ws = self._book.add_worksheet(title=CONFIG_TAB, rows=40, cols=3)
        ws.append_rows(
            [
                ["Setting", "Value", "What this does"],
                ["ENABLED", "TRUE",
                 "Set to FALSE to stop the agent. It will not run again until you set it "
                 "back to TRUE. Nobody else needs to be involved."],
                ["MIN_AWARD", str(MIN_AWARD_PLACEHOLDER),
                 "PLACEHOLDER — please replace. The smallest award worth 10 hours of the "
                 "team's time. Anything smaller is not shown to you at all. This is the "
                 "single most important setting on this page."],
                ["MAX_OPPORTUNITIES", "12",
                 "How many results to bring you each week. Sized for a one-hour review."],
                ["PROGRAMS_ACTIVE", "RULFP, RESILIENCE, ARTS",
                 "Which programs to search for. Remove one to pause it."],
                ["RUN_DAY", "Wednesday", "The day the agent goes looking."],
                ["RUN_TIME", "23:00",
                 "The time it runs, Pacific. Results are waiting Thursday morning."],
            ],
            value_input_option="USER_ENTERED",
        )
        ws.freeze(rows=1)
        log.info("Created the %s tab.", CONFIG_TAB)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
