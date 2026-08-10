"""Download-as-a-spreadsheet. Offline — no network, no API key, no model calls.

The interesting tests here are not "does it produce a CSV". They are:

  - a value the funder's page never stated must not gain one on the way out, and
  - a cell must not become a formula when the user opens the file.

The second is the one worth having. Titles come from scraped funder pages, and a
spreadsheet treats a leading '=' or '-' as executable. A grant titled "-30% match
required" is a plausible real title, not a contrived one.

    .venv/bin/python -m pytest tests/test_export.py -q
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

from app import export
from app.db import init_db


def rows_of(text: str) -> list[list[str]]:
    """Parse back exactly as a spreadsheet would, BOM stripped."""
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


OPP = {
    "id": "abc123",
    "score": 88,
    "score_rationale": "Warm funder, clears the floor, and the deadline leaves runway.",
    "source_kind": "funder_page",
    "funder": "Prebys Foundation",
    "title": "2027 Prebys Leadership Awards",
    "award_min": 50_000,
    "award_max": 250_000,
    "deadline": "2026-11-30",
    "days_left": 120,
    "estimated_effort_hours": 8,
    "program_match": ["RULFP", "ARTS"],
    "needs_human_check": False,
    "source_url": "https://example.invalid/leadership",
    "found_on": "2026-08-02",
}


# --- shape --------------------------------------------------------------------

def test_header_matches_the_sheet_layout():
    """The CSV and the Sheets sink are two renderings of one brief (app/export.py)."""
    from sinks.sheets import HEADERS as SHEET_HEADERS

    assert export.HEADERS == SHEET_HEADERS


def test_row_values_land_under_their_headers():
    header, row = rows_of(export.to_csv([OPP]))
    cell = dict(zip(header, row))

    assert cell["Score"] == "88"
    assert cell["Funder"] == "Prebys Foundation"
    assert cell["Award (low)"] == "50000"
    assert cell["Award (high)"] == "250000"
    assert cell["Deadline"] == "2026-11-30"
    assert cell["Est. hours"] == "8"
    assert cell["Programs"] == "RULFP, ARTS"
    assert cell["Link"] == "https://example.invalid/leadership"
    assert cell["Where it came from"] == "The funder's own page"


def test_empty_findings_still_produce_a_usable_file():
    """A quiet week downloads a header row, not a broken file."""
    assert rows_of(export.to_csv([])) == [export.HEADERS]


# --- the promise the whole project rests on (CLAUDE.md) --------------------

def test_a_missing_award_stays_missing():
    """Null in the DB must be blank in the file — never a 0, never a guess."""
    sparse = {**OPP, "award_min": None, "award_max": None,
              "deadline": None, "estimated_effort_hours": None}
    header, row = rows_of(export.to_csv([sparse]))
    cell = dict(zip(header, row))

    for column in ("Award (low)", "Award (high)", "Deadline", "Est. hours"):
        assert cell[column] == "", f"{column} invented a value"


def test_needs_human_check_survives_the_export():
    header, row = rows_of(export.to_csv([{**OPP, "needs_human_check": True}]))
    assert dict(zip(header, row))["Needs a human check"] == "yes"


# --- spreadsheet safety -------------------------------------------------------

@pytest.mark.parametrize("hostile", ["=1+1", "+SUM(A1)", "-30% match required",
                                     "@import", '=HYPERLINK("http://evil.invalid")'])
def test_a_title_cannot_become_a_formula(hostile):
    """Scraped text opens as text. Excel and Sheets both execute a leading = + - @."""
    header, row = rows_of(export.to_csv([{**OPP, "title": hostile}]))
    title = dict(zip(header, row))["Opportunity"]

    assert title.startswith("'"), f"{hostile!r} would execute on open"
    assert title.lstrip("'") == hostile, "the original text was altered, not just quoted"


def test_a_rationale_containing_commas_and_quotes_round_trips():
    """One sentence, one cell — not three columns."""
    messy = 'Warm funder, clears $50,000, and they call it a "leadership" award.'
    header, row = rows_of(export.to_csv([{**OPP, "score_rationale": messy}]))

    assert len(row) == len(header)
    assert dict(zip(header, row))["Why this one"] == messy


def test_newlines_are_flattened_so_a_row_stays_one_row():
    header, row = rows_of(export.to_csv([{**OPP, "score_rationale": "line one\nline two"}]))
    assert dict(zip(header, row))["Why this one"] == "line one line two"


def test_file_is_utf8_bom_so_excel_reads_accents():
    assert export.to_csv([]).startswith("﻿")


# --- the route ----------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    init_db()
    seed_starter_funders()
    seed_starter_programs()

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def test_endpoint_downloads_rather_than_renders(client):
    res = client.get("/api/opportunities/export.csv")

    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    # Without this the browser shows the CSV as a wall of text instead of saving it.
    assert "attachment" in res.headers["content-disposition"]
    assert ".csv" in res.headers["content-disposition"]


def test_filename_names_the_month_being_downloaded(client):
    res = client.get("/api/opportunities/export.csv?month=2026-07")
    assert 'filename="fundworthy-funding-2026-07.csv"' in res.headers["content-disposition"]


def test_the_download_is_named_after_the_organization_that_asked_for_it(client):
    """It used to be `rise-funding-…` for everybody — the pilot organisation's name,
    hardcoded, on a file downloaded by whichever nonprofit pressed the button. Same class
    of mistake as the borrowed "Existing relationship" chip: our data asserting something
    about them."""
    client.put("/api/settings", json={"org_name": "Casa Familiar"})
    res = client.get("/api/opportunities/export.csv?month=2026-07")
    assert 'filename="casa-familiar-funding-2026-07.csv"' in \
        res.headers["content-disposition"]


def test_a_name_cannot_smuggle_anything_into_the_download_header(client):
    """The org name is attacker-controlled text going into a Content-Disposition header,
    where a quote or a newline is header injection rather than a cosmetic problem."""
    client.put("/api/settings", json={"org_name": 'ev"il\r\nX-Injected: yes'})
    header = client.get("/api/opportunities/export.csv").headers["content-disposition"]

    assert '"' not in header.split("filename=")[1].strip('"')
    assert "\n" not in header and "\r" not in header
    assert "X-Injected" not in header


def test_an_unnamed_organization_gets_a_neutral_name_not_a_guess(client):
    """Blank is a real state — the Settings page says so — and the file should not
    invent one."""
    res = client.get("/api/opportunities/export.csv")
    assert 'filename="fundworthy-funding.csv"' in res.headers["content-disposition"] or \
        'filename="fundworthy-funding-' in res.headers["content-disposition"]


def test_accents_survive_as_readable_ascii(client):
    """"Fundación" must not become an empty slug, which would silently fall back to the
    neutral name and lose the org from its own filename."""
    from app.export import filename

    assert filename("2026-07", "Fundación Comunitaria") == \
        "fundacion-comunitaria-funding-2026-07.csv"


def test_export_never_leaks_the_api_key(client):
    """Same guarantee test_api.py makes of every other endpoint."""
    key = "sk-ant-api03-THIS-IS-NOT-A-REAL-KEY-0000000000-4f2a"
    client.post("/api/settings/api-key", json={"api_key": key})

    assert key not in client.get("/api/opportunities/export.csv").text


# --- picking which searches to print, from Past findings -----------------------

def _seeded_run(client, run_id, title, source_url):
    """One search, one finding, wired the way the pipeline actually writes them —
    not a bare INSERT, so this exercises the same upsert `save_opportunity` uses in
    production."""
    from datetime import date, datetime, timedelta, timezone

    from agent.models import Opportunity, stable_id
    from app import repo
    from app.db import DEFAULT_ORG_ID, session

    with session() as conn:
        repo.create_run(conn, run_id, org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(
            conn,
            Opportunity(
                id=stable_id(source_url, title),
                title=title, funder="Example Foundation", source_url=source_url,
                award_min=10_000, award_max=50_000,
                deadline=date.today() + timedelta(days=60),
                estimated_effort_hours=8, program_match=[], score=72,
                score_rationale="fits", verified=True, needs_human_check=False,
                fetched_at=datetime.now(timezone.utc),
            ),
            run_id=run_id, org_id=DEFAULT_ORG_ID,
        )


def test_run_ids_narrows_the_export_to_the_selected_searches(client):
    """The Past findings picker: 'Aug 7 10am' and 'Aug 6 1pm' together, everything
    else from the month left out."""
    _seeded_run(client, "r-1", "Morning grant", "https://example.invalid/morning")
    _seeded_run(client, "r-2", "Afternoon grant", "https://example.invalid/afternoon")
    _seeded_run(client, "r-3", "Evening grant", "https://example.invalid/evening")

    res = client.get("/api/opportunities/export.csv?run_ids=r-1,r-2")
    rows = rows_of(res.text)
    titles = {r[rows[0].index("Opportunity")] for r in rows[1:]}

    assert titles == {"Morning grant", "Afternoon grant"}
    assert "Evening grant" not in titles


def test_a_single_run_id_still_works_alongside_run_ids(client):
    """Backward compatibility: the singular `run_id` param (used elsewhere, e.g. a
    search card's own "show these findings" link) still narrows to one search when
    `run_ids` is not given at all."""
    _seeded_run(client, "r-solo", "Solo grant", "https://example.invalid/solo")
    _seeded_run(client, "r-other", "Other grant", "https://example.invalid/other")

    res = client.get("/api/opportunities/export.csv?run_id=r-solo")
    rows = rows_of(res.text)
    titles = {r[rows[0].index("Opportunity")] for r in rows[1:]}

    assert titles == {"Solo grant"}
