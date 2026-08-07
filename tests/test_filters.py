"""The tier-1 free deterministic filters (`agent/filters.py`) — "the whole cost
strategy" per that module's own docstring, and previously untested. Everything here
runs offline with no API key and no network, killing candidates at $0 before a single
model call.

The one rule this file exists to protect is the null-vs-reject distinction the module
docstring calls out by name: a filter that rejects nulls empties the pipeline, and one
that passes them silently defeats the award floor, which is the entire product.
"""

from __future__ import annotations

from datetime import date, timedelta

from agent.config import Config
from agent.filters import Flag, Reject, apply_filters
from agent.parse import Evidence, ParsedPage


def _page(*, title="A Grant", url="https://example.invalid/grants", text="",
          award_max=None, deadline=None) -> ParsedPage:
    amounts = [Evidence(value=award_max, snippet="$", kind="amount")] if award_max is not None else []
    deadlines = [Evidence(value=deadline, snippet="due", kind="deadline")] if deadline is not None else []
    return ParsedPage(url=url, title=title, text=text, amounts=amounts, deadlines=deadlines)


def test_an_award_below_the_floor_is_rejected_for_free():
    page = _page(award_max=4_000)
    result = apply_filters(page, "Example Foundation", Config())
    assert result.rejected
    assert result.reason is Reject.BELOW_MIN_AWARD
    assert "4,000" in result.detail and "10,000" in result.detail


def test_an_award_at_or_above_the_floor_survives():
    page = _page(award_max=10_000)
    result = apply_filters(page, "Example Foundation", Config())
    assert not result.rejected


def test_a_missing_award_is_flagged_never_rejected():
    """The rule the module docstring calls the entire product: silence about the
    amount is not a reject, or the award floor would be defeated for every page that
    just doesn't publish a number — which CLAUDE.md says is most of them."""
    page = _page(award_max=None)
    result = apply_filters(page, "Example Foundation", Config())
    assert not result.rejected
    assert Flag.AMOUNT_NOT_STATED in result.flags


def test_a_deadline_inside_the_runway_is_rejected():
    page = _page(award_max=50_000, deadline=date.today() + timedelta(days=3))
    result = apply_filters(page, "Example Foundation", Config(min_deadline_runway_days=14))
    assert result.rejected
    assert result.reason is Reject.DEADLINE_TOO_SOON


def test_a_deadline_with_enough_runway_survives():
    page = _page(award_max=50_000, deadline=date.today() + timedelta(days=60))
    result = apply_filters(page, "Example Foundation", Config(min_deadline_runway_days=14))
    assert not result.rejected


def test_a_missing_deadline_is_flagged_never_rejected():
    page = _page(award_max=50_000, deadline=None)
    result = apply_filters(page, "Example Foundation", Config())
    assert not result.rejected
    assert Flag.DEADLINE_NOT_STATED in result.flags


def test_a_religious_organization_is_rejected_on_the_funder_name():
    page = _page(award_max=50_000)
    result = apply_filters(page, "First Baptist Church Foundation", Config())
    assert result.rejected
    assert result.reason is Reject.RELIGIOUS


def test_a_political_party_is_rejected_on_the_funder_name():
    page = _page(award_max=50_000)
    result = apply_filters(page, "State Democratic Party Committee", Config())
    assert result.rejected
    assert result.reason is Reject.POLITICAL


def test_a_non_opportunity_page_is_rejected_on_title():
    page = _page(title="Call for Panelists — FY26 Review Committee", award_max=50_000)
    result = apply_filters(page, "Example Foundation", Config())
    assert result.rejected
    assert result.reason is Reject.NOT_AN_OPPORTUNITY


def test_a_match_requirement_is_flagged_never_rejected():
    """§11 Q4 is unanswered — the org's own match capacity isn't known, so this can
    only ever be a flag a human reads, never a silent reject."""
    page = _page(award_max=50_000,
                 text="Applicants must provide a 1:1 match of all requested funds.")
    result = apply_filters(page, "Example Foundation", Config())
    assert not result.rejected
    assert Flag.MATCH_REQUIREMENT in result.flags


def test_the_lowest_ticked_program_floor_is_used_not_the_global_one():
    """Filtering at the highest floor would kill a program's opportunities before
    program-aware scoring ever saw them — see the comment in apply_filters."""
    from agent.config import ProgramCard

    cfg = Config(programs=[
        ProgramCard(slug="arts", name="Arts", min_award=5_000),
        ProgramCard(slug="other", name="Other", min_award=10_000),
    ])
    page = _page(award_max=6_000)
    result = apply_filters(page, "Example Foundation", cfg)
    assert not result.rejected, "6,000 clears the lowest ticked program's floor (5,000)"


def test_first_reject_wins_religious_before_award_floor():
    """Order matters for the message a human eventually reads. A religious-organization
    reject is unambiguous; a below-floor reject on the same page would be a worse
    explanation even if also true."""
    page = _page(award_max=100)
    result = apply_filters(page, "Diocese of Somewhere", Config())
    assert result.reason is Reject.RELIGIOUS


# Note on `Reject.DEADLINE_PASSED`: as wired today it is unreachable through
# `apply_filters`. `ParsedPage.earliest_deadline` (agent/parse.py) only ever returns a
# date that is `>= date.today()` — a page whose only deadline evidence is in the past
# resolves to `None`, which routes to `Flag.DEADLINE_NOT_STATED` instead. So the
# `days < 0` branch in `apply_filters` can never fire via a real parsed page. Not
# fixed here — it isn't one of the four correctness bugs this pass targeted, and
# changing which of "not stated" vs "passed" an expired-only deadline should mean is a
# product call, not a test-writing one. Flagged in FUTURE.md instead.
