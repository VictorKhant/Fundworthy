"""The free-tier extraction that decides what a candidate's amount and deadline ARE
(agent/parse.py: extract_amounts, extract_deadlines) — offline, no key, no network.

Found by fetching 62 real funder pages from the shipped registry (agent/sd_funders.py,
agent/sources.py) and comparing what a human reading the page sees against what the
parser extracted. The excerpts below are literal text copied from those real pages, not
invented strings, and are attributed to their funder and URL so a future reader can go
look at the source themselves.

The root cause behind every deadline/amount case here was one function:
`_sentences()` split on a bare `:` as if it ended a sentence, so "Deadline to apply: May
1, 2027" — one fact, one line — came apart into a label with no date and a date with no
label, and extract_deadlines requires both in the same piece. Measured against the real
sample, `label: value` on one line, or a table rendering the label and the value on
adjacent lines, is how MOST funders publish this — not an edge case.

The proximity/disqualifier tests exist because loosening the extractor to catch these
cases opened two new ways to be CONFIDENTLY WRONG, which is worse than the miss this file
is otherwise fixing (CLAUDE.md §6: no URL, no record; the same rule applies to a wrong
date or a wrong amount attributed to a real URL). Both were found the same way — by
running the fix against real pages and reading what came out, not by guessing at edge
cases in the abstract.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.parse import extract_amounts, extract_deadlines, parse_page  # noqa: E402


# --- the core bug: label and value in different chunks -------------------------

def test_a_colon_separated_deadline_on_one_line_is_found():
    """Port of San Diego, Tidelands Activation Programs — the whole thing is one line:
    "Deadline to apply: May 1, 2027 - 5:00 p.m." The colon used to split it into a
    cue with no date and a date with no cue."""
    text = "Click here to Apply\n\nDeadline to apply: May 1, 2027 - 5:00 p.m.\n\nA Day at the Park"
    found = extract_deadlines(text)
    assert [e.value for e in found] == [date(2027, 5, 1)]


def test_a_colon_separated_award_amount_on_one_line_is_found():
    """The identical bug hit extract_amounts too — the same `_sentences()` split, the
    same coupling requirement. "Award Amount:\\n$50,000" with nothing else on either
    line found nothing before this fix."""
    text = "Award Amount:\n$50,000"
    found = extract_amounts(text)
    assert [e.value for e in found] == [50_000]


def test_a_deadline_on_the_line_after_its_label_is_found():
    """Alliance for California Traditional Arts, Living Cultures Grant:
    "Application closes:\\nApril 27, 2026" — a real table row, label above value."""
    text = "Application opens:\nMarch 3, 2026\n\nApplication closes:\nApril 27, 2026\n\nGrant notifications:\nAugust 2026"
    found = extract_deadlines(text)
    assert date(2026, 4, 27) in [e.value for e in found]


def test_a_deadline_extended_notice_is_found():
    """The Human Dignity Foundation: "Deadline extended to: March 14, 2026" — a real
    cue phrase (`extended to`) this parser's cue list did not need to change for; the
    fix was purely getting the cue and the date into the same unit."""
    text = "In keeping with our funding priorities.\n\nDeadline extended to: March 14, 2026\n\nGrant Requirements"
    found = extract_deadlines(text)
    assert [e.value for e in found] == [date(2026, 3, 14)]


def test_a_labeled_bid_due_date_with_a_time_is_found():
    """San Diego Workforce Partnership: "Bid Due Date: 07/09/2026 3:00 PM (PDT)" — a
    numeric date format, colon-separated, with trailing text after the date."""
    text = "Bid Due Date: 07/09/2026 3:00 PM (PDT)\n\nScope of Services"
    found = extract_deadlines(text)
    assert date(2026, 7, 9) in [e.value for e in found]


# --- the false-positive this fix could have introduced, and did not ------------

def test_a_may_deadline_is_recorded_once_not_twice():
    """May's abbreviation IS its full spelling, so "May 1, 2027" matched both the
    full-month and the abbreviated-month pattern and was recorded as two separate
    pieces of evidence for the same date."""
    text = "Deadline to apply: May 1, 2027 - 5:00 p.m."
    found = extract_deadlines(text)
    assert len(found) == 1, f"expected one Evidence for one date, got {len(found)}"


def test_a_multi_row_timeline_table_does_not_bleed_dates_between_rows():
    """National Endowment for the Arts, Grants for Arts Projects — a real timeline
    table with FIVE distinct milestones (guidelines published, portal opens,
    submission deadline, portal opens again, submission deadline again, notification,
    project start), each on its own line, two funding cycles side by side.

    A first attempt at this fix loosened newline-splitting to "2+ newlines = a
    break", which let this whole table collapse into one giant sentence — the cue
    "deadline" matched once, and every date in the table (including the "opens to
    applicants" date and, in a fuller excerpt, the notification date) was extracted
    as if it were a deadline. Single newlines still split chunks apart specifically
    so this cannot happen — table rows a real funder renders one per line must stay
    one per line.
    """
    text = (
        "Part 1 Application Package Available on Grants.gov\n"
        "Early December 2025\n"
        "Part 1 Grants.gov\n"
        "Submission deadline\n\n"
        "February 12, 2026\n"
        "11:59 pm Eastern\n"
        "Time\n"
        "Part 2 NEA Applicant Portal\n"
        "Opens to applicants\n"
        "February 18, 2026\n"
        "9:00 am Eastern\n"
        "Time\n"
        "Part 2 NEA Applicant Portal\n"
        "Submission deadline\n"
        "February 25, 2026\n"
        "11:59 pm Eastern Time\n"
        "Notification of recommended funding\n"
        "November 2026\n"
        "Earliest project start date\n"
        "January 1, 2027\n"
    )
    found = {e.value for e in extract_deadlines(text)}
    # The two real submission deadlines.
    assert date(2026, 2, 12) in found
    assert date(2026, 2, 25) in found
    # Not the portal-opens date, the notification date, or the project-start date —
    # none of those are the deadline, whatever cue word happens to share a line-run
    # with them elsewhere in the table.
    assert date(2026, 2, 18) not in found, "an 'opens' date was recorded as a deadline"
    assert date(2027, 1, 1) not in found, "a project-start date was recorded as a deadline"


def test_an_open_date_is_not_reported_as_the_deadline():
    """San Diego Pride's grants page, verbatim: "Applications open: Monday, October
    6th, 2025 Deadline to apply: Monday, November 3rd, 2025" — no sentence break
    between them at all, both dates in one run.

    This is not hypothetical: the CODE IN PRODUCTION BEFORE THIS FIX reported October
    6 — the open date — as the deadline, because the old `:`-splitting boundary
    happened to land between "open" and "Deadline", putting October 6 in the same
    chunk as the words "Deadline to apply:". `ParsedPage.earliest_deadline` takes the
    MIN of whatever it is given, and an open date is always earlier than the deadline
    that follows it — so this silently swaps in a date that was never the deadline at
    all. This test locks the FIX, not a hypothetical: only November 3 may appear.
    """
    text = ("2026 Grant Cycle Key Deadlines Applications open: Monday, October 6th, "
            "2025 Deadline to apply: Monday, November 3rd, 2025 Award notifications: "
            "First week of December")
    found = [e.value for e in extract_deadlines(text)]
    assert found == [date(2025, 11, 3)], (
        f"expected only the real deadline, got {found} — an open date leaked through"
    )


def test_an_already_awarded_grant_record_is_not_read_as_an_open_award_size():
    """Hilton Foundation's housing priorities page lists past grants as case studies:
    "Grant Amount:\\n$2400000\\n\\nAwarded Date:\\nAugust, 2022\\n\\nProject Start
    Date:\\nSeptember, 2022". This is a record of a grant already given, not an open
    call's award size — "Awarded Date" two lines below the figure is the signal, and
    a check that only looked at the bare value line would never see it."""
    text = ("Grant Amount:\n$2400000\n\nAwarded Date:\nAugust, 2022\n\n"
            "Project Start Date:\nSeptember, 2022")
    found = extract_amounts(text)
    assert found == [], f"a historical award record was read as an open call's amount: {found}"


# --- a stated floor is not a ceiling ------------------------------------------

def test_a_lone_minimum_grant_size_does_not_become_the_award_max():
    """Hearst Foundations, Health funding priorities, verbatim: "Minimum grant size is
    $100,000." That is a floor, not a ceiling — the page never says awards top out
    there. `award_min` and `award_max` used to both resolve to the same min()/max() over
    one evidence value, so the stated floor was reported as the cap, which would tell a
    nonprofit a $2M-a-year health funder caps out at $100k."""
    text = "Minimum grant size is $100,000."
    found = extract_amounts(text)
    assert [e.value for e in found] == [100_000]
    assert found[0].floor_only is True


def test_parse_page_leaves_award_max_unset_for_a_lone_stated_floor_end_to_end():
    html = (
        "<html><head><title>Health — Funding Priorities</title></head><body>"
        "<p>Minimum grant size is $100,000.</p>"
        "</body></html>"
    )
    page = parse_page("https://example.invalid/health", html)
    assert page.award_min == 100_000
    assert page.award_max is None, (
        "a lone stated floor was reported as the award ceiling"
    )


def test_a_range_stating_both_a_floor_and_a_ceiling_is_unaffected():
    """A sentence that names both ends is not "floor-only" — both numbers are real
    evidence for their own side, same as before this fix existed."""
    text = "Grants of $5,000 up to $50,000 are available to eligible nonprofits."
    found = extract_amounts(text)
    assert {e.value for e in found} == {5_000, 50_000}
    assert all(not e.floor_only for e in found)


def test_an_up_to_ceiling_with_no_floor_language_is_unaffected():
    text = "Awards of up to $75,000 are available."
    found = extract_amounts(text)
    assert [e.value for e in found] == [75_000]
    assert found[0].floor_only is False


def test_a_genuine_open_call_amount_still_passes_near_unrelated_disqualifier_text():
    """The disqualifier-lookahead fix above must not become trigger-happy: a real
    award figure followed (a few lines later) by an unrelated deadline label must
    still be extracted."""
    text = "Award Amount:\n$50,000\n\nApplication Deadline:\nMarch 1, 2027"
    found = extract_amounts(text)
    assert [e.value for e in found] == [50_000]


# --- a century-off deadline, found the same way -------------------------------

def test_a_two_digit_year_date_is_not_parsed_a_century_in_the_future():
    """California Board of State and Community Corrections, CalVIP grant, verbatim:
    "Proposals due 6/27/25." `dateparser`'s own `PREFER_DATES_FROM: "future"` setting
    parsed this as 2125-06-27 — a century off, not 2025 — because a 2-digit year is
    ambiguous and dateparser resolved the ambiguity toward the far future instead of
    the nearby one. Since `ParsedPage.earliest_deadline` only ever returns a future
    date and takes the MIN, a date wrongly parsed a century ahead would always look
    like the deadline with unlimited runway — exactly backwards for a grant whose
    real 2025 deadline had already passed. A page fetched today writing a 2-digit
    year never means anything but this century."""
    text = "Proposals due 6/27/25 for the CalVIP grant program."
    found = extract_deadlines(text)
    assert [e.value for e in found] == [date(2025, 6, 27)], (
        f"expected 2025, not a date a century off: {found}"
    )


def test_two_digit_years_across_the_century_boundary_resolve_sanely():
    """Not just the one real case — every 2-digit year on a page fetched today has to
    land in a sane range, not just the specific "25" that broke."""
    from agent.parse import _parse_date

    assert _parse_date("1/1/00") == date(2000, 1, 1)
    assert _parse_date("12/31/99") == date(2099, 12, 31)
    assert _parse_date("6/27/25") == date(2025, 6, 27)


def test_a_four_digit_year_date_is_unaffected_by_the_two_digit_fix():
    assert extract_deadlines("Proposals due 6/27/2025.")[0].value == date(2025, 6, 27)


# --- guardrails the fix must not weaken ------------------------------------------

def test_an_unrelated_date_near_a_cue_word_is_still_not_paired():
    """The proximity pairing is deliberately narrow. A cue line followed by something
    that is NOT a bare date must not reach further down the page hunting for one."""
    text = "Deadline:\nContact us for more information.\n\nMarch 1, 2027 is a holiday."
    found = extract_deadlines(text)
    assert found == [], "paired a cue with a date two lines past an unrelated line"


def test_a_long_paragraph_containing_a_cue_word_is_not_treated_as_a_label():
    """`_paired_with_nearby_value` only fires for short, label-like lines. A paragraph
    that happens to use the word "deadline" in passing must go through the ordinary
    same-sentence path only, not the proximity pairing."""
    text = (
        "We recognize that nonprofits juggle many priorities and a hard deadline can "
        "be difficult to plan around, which is why we built flexibility into our "
        "review process for organizations that need it.\nMarch 1, 2027"
    )
    found = extract_deadlines(text)
    assert found == [], "a long unrelated paragraph was treated as a label for the next line"


# --- end to end through the real page-parsing entrypoint ------------------------

def test_parse_page_surfaces_a_table_style_deadline_end_to_end():
    """The same fix, exercised through `parse_page` — the actual function the pipeline
    calls — not just the extraction helpers directly."""
    html = (
        "<html><head><title>Community Grants</title></head><body>"
        "<p>Grants of up to $75,000 are awarded to eligible nonprofits.</p>"
        "<p>Application Deadline</p>"
        "<p>October 15, 2026</p>"
        "</body></html>"
    )
    page = parse_page("https://example.invalid/grants", html)
    assert page.award_max == 75_000
    assert page.earliest_deadline == date(2026, 10, 15), (
        "a label-above-value deadline was not surfaced through parse_page"
    )


def test_parse_page_does_not_confuse_an_open_date_with_the_deadline_end_to_end():
    html = (
        "<html><head><title>2026 Grant Cycle</title></head><body>"
        "<p>Grants of up to $10,000 are awarded to nonprofits.</p>"
        "<p>2026 Grant Cycle Key Deadlines Applications open: Monday, October 6th, "
        f"{date.today().year + 1} Deadline to apply: Monday, November 3rd, "
        f"{date.today().year + 1}.</p>"
        "</body></html>"
    )
    page = parse_page("https://example.invalid/grants", html)
    assert page.earliest_deadline == date(date.today().year + 1, 11, 3)
