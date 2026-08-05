"""Download the findings as a spreadsheet file. (CLAUDE.md)

B3 demoted the Google Sheet from "the product" to an export target, and CLAUDE.md
§Phase 3 scoped that export as an OAuth push into their live Sheet. This is the smaller
thing that gets them the same outcome today: a CSV they open in Sheets, Excel, or
Numbers. No Google API, no consent screen, no service account, no credential to
rotate — which is also why it cannot break on a Thursday morning.

The column order is copied from `sinks/sheets.py`, deliberately. the user already reads
that layout left to right (score, then why, then who), and a second layout would be a
second thing to learn for no benefit.
"""

from __future__ import annotations

import csv
import io

# Same order and wording as sinks/sheets.py HEADERS. If you change one, change both —
# they are two renderings of the same brief, and they should not be able to tell which
# one they are looking at.
HEADERS = [
    "Score",
    "Why this one",
    "Where it came from",
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
    "Their 990",             # shown as data, never scored — their call
    "Programs",
    "Needs a human check",
    "Link",
    "Found on",
    "id",
]

SOURCE_KIND_LABELS = {
    "funder_page": "The funder's own page",
    "indexed_database": "Public grants database",
}

# Excel and Google Sheets both treat a leading =, +, -, or @ as the start of a formula.
# Our text comes from scraped funder pages, so a title beginning with "-" is not
# hypothetical. Prefixing with an apostrophe makes the cell literal text; the apostrophe
# is not shown once the file is opened.
_FORMULA_LEAD = ("=", "+", "-", "@")


def _safe(value) -> str:
    """One cell, rendered as text a spreadsheet will not try to execute."""
    if value is None or value is False:
        return ""
    if value is True:
        return "yes"
    if isinstance(value, (list, tuple)):
        return ", ".join(_safe(v) for v in value if v not in (None, ""))
    text = str(value).replace("\r\n", " ").replace("\n", " ").strip()
    if text.startswith(_FORMULA_LEAD):
        return "'" + text
    return text


def _row(opp: dict) -> list[str]:
    kind = opp.get("source_kind")
    return [
        _safe(opp.get("score")),
        _safe(opp.get("score_rationale")),
        _safe(SOURCE_KIND_LABELS.get(kind, kind)),
        _safe(opp.get("funder")),
        _safe(opp.get("title")),
        _safe(opp.get("award_min")),
        _safe(opp.get("award_max")),
        _safe(opp.get("deadline")),
        _safe(opp.get("days_left")),
        _safe(opp.get("estimated_effort_hours")),
        _safe(opp.get("application_lead_time_days")),
        _safe(round(opp["time_to_funds_days"] / 30) if opp.get("time_to_funds_days") else None),
        _safe(opp.get("confidence_pct")),
        _safe(opp.get("form_990_url")),
        _safe(opp.get("program_match")),
        "yes" if opp.get("needs_human_check") else "",
        _safe(opp.get("source_url")),
        _safe(opp.get("found_on")),
        _safe(opp.get("id")),
    ]


def to_csv(opportunities: list[dict]) -> str:
    """Render the brief as CSV text.

    Rows are written in the order given. Callers pass what `repo.list_opportunities`
    returned, which is already sorted the way the user asked to read it — clean results
    first, the ones needing their judgement last — so the file, the dashboard, and the
    Sheet all agree without any of them re-deriving the order.
    """
    buf = io.StringIO()
    # QUOTE_MINIMAL with the default dialect: rationales contain commas, and every
    # spreadsheet reads RFC-4180 quoting correctly.
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for opp in opportunities:
        writer.writerow(_row(opp))
    # Excel on Windows assumes the system codepage for a bare .csv and mangles the
    # accented names in this data. The BOM makes it read UTF-8; Sheets and Numbers
    # both skip it silently.
    return "﻿" + buf.getvalue()


def filename(month: str | None) -> str:
    """A name that still means something in a Downloads folder six weeks from now."""
    return f"rise-funding-{month}.csv" if month else "rise-funding.csv"
