"""The Google Sheets sink — the product. (CLAUDE.md)

the user's whole surface area is this Sheet: they read Opportunities, edit Config, and
turn the agent off from a cell. So the rendering rules matter as much as the data:

  - score_rationale sits in a column they can read without scrolling (§9).
  - Rows whose award amount was never stated go in their own block below the ranked
    list, clearly labeled, so they cannot be mistaken for scored results.
  - Each run archives last week's brief to a dated "Archive <date>" tab, then writes
    this week fresh — so the live Opportunities tab is always the current week's brief
    (sorted, one-hour review), and nothing is ever destroyed. If the agent is wrong,
    the snapshot is still there.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent.models import Opportunity, RunLog, _enum_value, SourceKind

from .base import coverage_banner, split_sections

log = logging.getLogger(__name__)

OPPORTUNITIES_TAB = "Opportunities"
RUNS_TAB = "Runs"
ARCHIVE_PREFIX = "Archive"   # last week's brief is snapshotted to "Archive <date>"

HEADERS = [
    "Score",
    "Why this one",          # score_rationale — kept early, they read left to right
    "Where it came from",    # provenance — a curated funder page vs a public database
    "Funder",
    "Opportunity",
    "Award (low)",
    "Award (high)",
    "Deadline",
    "Days left",
    "Est. hours",
    # The COO's own ranking criteria (§11 Q5). Two different kinds of time, which they
    # separated: days to BE READY to submit, vs days from submitting to money arriving.
    "Days to prepare",
    "Months to funds",
    "Fit %",                 # the AI's own confidence — inferred, labelled in the UI
    "Programs",
    "Needs a human check",
    "Link",
    "Found on",
    "id",                    # last: bookkeeping, not for reading
]

# New columns go on the END, never in the middle. The Runs tab is append-only and
# already has history in it; inserting a column would leave every existing row's
# values sitting one column left of the header that now names them.
RUN_HEADERS = [
    "When it ran", "Minutes", "Funders checked", "Couldn't reach",
    "Pages read", "Ruled out for free", "Brought to you", "Amount not stated",
    "Cost", "How it ended", "Notes",
    "Which ones failed",
]

# §9: no technical vocabulary on anything the user reads. StopReason values are for
# the log and the dashboard; this is what they see.
STOP_REASON_PLAIN = {
    "target_met": "Found enough — stopped at the weekly limit",
    "budget": "Hit the spending limit for the week and stopped",
    "sources_exhausted": "Checked every funder on the list",
    "disabled": "You had turned it off (ENABLED was FALSE)",
    "error": "Something went wrong — see Notes",
    "partial": "Something broke partway — the results above are what it got first",
}

SECTION_BANNER = (
    "AMOUNT NOT STATED ON THE FUNDER'S PAGE — these need a human look. "
    "They are not ranked, because there is no award amount to rank them by."
)

KIND_BANNER = {
    SourceKind.FUNDER_PAGE: (
        "FROM FUNDERS WE WATCH DIRECTLY — read off the funder's own page. These are "
        "organizations on the organization's list, several of them already warm."
    ),
    SourceKind.INDEXED_DATABASE: (
        "FROM PUBLIC GRANT DATABASES — the California Grants Portal and Grants.gov. "
        "Complete public lists, so these are cold leads: nobody at the organization has a "
        "relationship with these funders yet."
    ),
}


# Everything the user reads is in their own timezone. The agent runs Wednesday 11pm PT so
# the brief is waiting Thursday morning (§9) — in UTC that run is stamped Thursday,
# which reads as a day late for a job that ran on time.
#
# The zone is America/Los_Angeles, not a fixed -8 offset: Pacific is PDT for most of
# the year and PST only from November to March. %Z prints whichever is actually in
# force, so the label is never wrong by an hour.
PACIFIC = ZoneInfo("America/Los_Angeles")


def _pacific(when: datetime) -> datetime:
    """UTC timestamp -> Pacific. Naive datetimes are assumed UTC, which is what the
    agent produces (`datetime.now(timezone.utc)`)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(PACIFIC)


def _fmt_money(value: int | None) -> str:
    return f"${value:,}" if value is not None else ""


def _row(opp: Opportunity) -> list:
    days = opp.days_until_deadline
    return [
        opp.score if opp.award_max is not None else "",
        opp.score_rationale,
        opp.source_kind.label,
        opp.funder,
        opp.title,
        _fmt_money(opp.award_min),
        _fmt_money(opp.award_max),
        opp.deadline.isoformat() if opp.deadline else "not stated",
        days if days is not None else "",
        opp.estimated_effort_hours if opp.estimated_effort_hours is not None else "",
        opp.application_lead_time_days if opp.application_lead_time_days is not None else "",
        round(opp.time_to_funds_days / 30) if opp.time_to_funds_days else "",
        opp.confidence_pct if opp.confidence_pct is not None else "",
        ", ".join(_enum_value(p) for p in opp.program_match),
        "YES" if opp.needs_human_check else "",
        opp.source_url,
        # Pacific, so "Found on" matches the day the run actually happened. A late
        # Wednesday-night run is already Thursday in UTC.
        _pacific(opp.fetched_at).strftime("%Y-%m-%d"),
        opp.id,
    ]


class SheetsSink:
    """Service-account write path. the user's only setup step is clicking Share (§4)."""

    name = "sheets"

    def __init__(self, sheet_id: str | None = None, credentials_path: str | None = None) -> None:
        self.sheet_id = sheet_id or os.environ.get("FUNDWORTHY_SHEET_ID")
        self.credentials_path = (
            credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
        if not self.sheet_id or not self.credentials_path:
            raise RuntimeError(
                "SheetsSink needs FUNDWORTHY_SHEET_ID and GOOGLE_APPLICATION_CREDENTIALS. "
                "Use --sink jsonl to run without credentials."
            )
        import gspread

        self._gc = gspread.service_account(filename=self.credentials_path)
        self._book = self._gc.open_by_key(self.sheet_id)

    def _tab(self, title: str, headers: list[str], *, rewritable: bool = False):
        """Fetch or create a tab, reconciling its header row with `headers`.

        `rewritable` says whether this tab's rows are replaced wholesale every run.
        It decides how far reconciliation is allowed to go:

        - Runs is append-only and holds history, so the header may only be *extended*
          on the right. Rewriting it would rename the columns sitting above existing
          rows, which silently changes what every past row claims to say.
        - Opportunities is archived and cleared on every write, so no row outlives its
          header. A full rewrite is safe there, and it is the only way a new column can
          be placed anywhere except last — which matters, because the user reads this tab
          left to right and provenance belongs near the front, not past the id column.
        """
        import gspread
        from gspread.utils import rowcol_to_a1

        try:
            ws = self._book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._book.add_worksheet(title=title, rows=200, cols=max(len(headers), 16))
            ws.append_row(headers, value_input_option="USER_ENTERED")
            ws.freeze(rows=1)
            return ws

        existing = ws.row_values(1)
        if existing == headers:
            return ws

        if rewritable:
            ws.update([headers], range_name="A1", value_input_option="USER_ENTERED")
            log.info("Rewrote the header row of %s (%d columns).", title, len(headers))
        elif len(existing) < len(headers) and headers[:len(existing)] == existing:
            ws.update(
                [headers[len(existing):]],
                range_name=rowcol_to_a1(1, len(existing) + 1),
                value_input_option="USER_ENTERED",
            )
            log.info("Added %d new column(s) to %s.", len(headers) - len(existing), title)
        else:
            log.warning(
                "%s has a header this version does not recognise (%d columns vs %d). "
                "Leaving it alone — reconciling it could misalign existing rows.",
                title, len(existing), len(headers),
            )
        return ws

    def _unique_title(self, base: str) -> str:
        """A worksheet title that doesn't collide (two runs on the same day, etc.)."""
        existing = {w.title for w in self._book.worksheets()}
        if base not in existing:
            return base
        n = 2
        while f"{base} ({n})" in existing:
            n += 1
        return f"{base} ({n})"

    def _archive_and_reset(self, ws) -> None:
        """Option C: snapshot last week's brief to a dated tab, then clear the live
        Opportunities tab so this run writes a clean current-week brief. Preserves
        history without ever letting weeks pile up in the tab the user reviews."""
        import re

        from gspread.utils import rowcol_to_a1

        values = ws.get_all_values()
        if len(values) <= 1:
            return  # header only (or empty) — nothing to archive, fresh start

        # Label the archive by when its opportunities were found (the "Found on"
        # column), so the tab name reflects the week it represents — not the run
        # that is now replacing it. Fall back to today if the column is empty.
        found_col = HEADERS.index("Found on")
        found = [r[found_col] for r in values[1:]
                 if len(r) > found_col and r[found_col].strip()]
        label = max(found) if found else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        ws.duplicate(new_sheet_name=self._unique_title(f"{ARCHIVE_PREFIX} {label}"))

        last_col = re.sub(r"\d+", "", rowcol_to_a1(1, len(HEADERS)))
        ws.batch_clear([f"A2:{last_col}"])

    @staticmethod
    def _banner(text: str) -> list:
        """A full-width label row. Text sits in the wide 'Why this one' column."""
        row = [""] * len(HEADERS)
        row[1] = text
        return row

    def write_opportunities(
        self, opportunities: list[Opportunity], run: RunLog | None = None
    ) -> int:
        scored, not_stated = split_sections(opportunities)
        ws = self._tab(OPPORTUNITIES_TAB, HEADERS, rewritable=True)
        self._archive_and_reset(ws)  # Option C: snapshot last week, start clean

        rows: list[list] = []

        # Coverage first, above the results. The Runs tab has the full picture, but
        # the user reviews this tab (§9) — so if a source was down, it has to say so
        # here, or they read a short list as a quiet week and never find out.
        banner = coverage_banner(run)
        if banner:
            for line in banner:
                row = [""] * len(HEADERS)
                row[1] = line
                rows.append(row)
            rows.append([""] * len(HEADERS))

        # Provenance is the top-level split, and scored/not-stated sits inside it.
        # The other way round buries it: a funder page that never publishes an award
        # amount lands entirely in the not-stated block, so a section headed "from
        # funders we watch" renders empty even on a week when four of them reported.
        # Where a record came from is the thing they need first — it decides whether
        # they are looking at a warm relationship or a cold lead.
        for kind in (SourceKind.FUNDER_PAGE, SourceKind.INDEXED_DATABASE):
            ranked = [o for o in scored if o.source_kind is kind]
            unranked = [o for o in not_stated if o.source_kind is kind]
            if not ranked and not unranked:
                continue

            rows.append(self._banner(KIND_BANNER[kind]))
            rows.extend(_row(o) for o in ranked)
            if unranked:
                rows.append(self._banner(SECTION_BANNER))
                rows.extend(_row(o) for o in unranked)
            rows.append([""] * len(HEADERS))

        if not rows:
            log.info("Nothing to write.")
            return 0

        ws.append_rows(rows, value_input_option="USER_ENTERED")
        # append_rows returns the count of rows, not of records — report records.
        log.info("Wrote %d ranked + %d amount-not-stated rows.", len(scored), len(not_stated))
        return len(scored) + len(not_stated)

    def write_run_log(self, run: RunLog) -> None:
        """One row per run. This is how the user can tell the agent is still alive —
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

        # Names, not just a count. "Couldn't reach: 2" is not actionable; "Couldn't
        # reach: Grants.gov, Prebys Foundation" tells them exactly what to check themselves.
        failed_names = ", ".join(h.funder for h in run.degraded_sources) or "—"

        ws.append_row(
            [
                _pacific(run.started_at).strftime("%Y-%m-%d %H:%M %Z"),
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
                failed_names,
            ],
            value_input_option="USER_ENTERED",
        )

    def ensure_config_tab(self) -> None:
        """Create the Config tab with plain-English labels if it is missing (§9).

        No technical vocabulary on this tab. the user has never seen a config file and
        should not be able to tell that this is one.
        """
        from agent.config import CONFIG_TAB, MIN_AWARD_DEFAULT

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
                ["MIN_AWARD", str(MIN_AWARD_DEFAULT),
                 "The smallest award worth 10 hours of the team's time. Anything smaller "
                 "is not shown to you at all. This is the single most important setting "
                 "on this page."],
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
