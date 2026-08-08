"""The scoring contract, and the metrics that decide whether a ranking is any good.

No API key, no network. Every question here is answerable from the composition rules and
the prompt text, which means it runs in CI on every change instead of needing somebody to
remember to spend a dollar.

The bug these were written against: the app returned eight findings scoring 13-42 out of
100, six of them inside a 7-point band, and every test in the repo passed. Two separate
causes, and each one now has a test that fails if it comes back.

  1  60 of the 100 points were conditioned on evidence most funder pages do not carry.
     `_SCORING_RULES` says so itself — "most funders publish neither an amount nor a
     deadline" — and then spent 35 points on the amount and 25 on the deadline. A page
     with neither was scored out of a de-facto 40 and ranked against pages scored out of
     100. That is `compose_score`, below.

  2  The org's identity never reached the prompt. `org_name` did not exist on Config at
     all and `org_location` was never passed to the scorer, so every tenant was screened
     as "a nonprofit working across San Diego County and Imperial County" — deciding the
     40-point fit component against the wrong region for everyone else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from agent.config import Config, ProgramCard  # noqa: E402
from agent.evalmetrics import (pair_accuracy, report, spearman,  # noqa: E402
                               spread)
from agent.score import (WEIGHTS, ScoreParts, _preamble, basis_note,  # noqa: E402
                         compose_score, org_context, scoring_schema)


# --- composition: the fix for the 42-point ceiling ----------------------------

def test_all_three_components_compose_to_the_stated_weights():
    """60/30/10 used to be three lines of English inside a prompt. Nothing enforced
    them, so the "weighted score" was one holistic guess at a sum described in prose."""
    assert sum(WEIGHTS.values()) == 100
    assert compose_score(ScoreParts(fit=60, award=30, timing=10)) == 100
    assert compose_score(ScoreParts(fit=0, award=0, timing=0)) == 0
    assert compose_score(ScoreParts(fit=30, award=15, timing=5)) == 50


def test_a_missing_component_leaves_the_denominator_instead_of_scoring_zero():
    """**The whole point.** A funder that does not publish an award amount has not
    offered a small grant; it has published a terse page.

    Same candidate, same fit, same timing. The only difference is whether the funder
    happened to print a number — and under the old rule that alone would have cost it
    outright."""
    with_award = ScoreParts(fit=42, award=21, timing=7)
    without = ScoreParts(fit=42, award=None, timing=7)

    assert compose_score(with_award) == 70       # 70/100 of the full scale
    assert compose_score(without) == 70          # 49/70, renormalised

    # And the old behaviour, for contrast: scoring the null as a zero.
    as_zero = ScoreParts(fit=42, award=0, timing=7)
    assert compose_score(as_zero) == 49
    assert compose_score(without) > compose_score(as_zero)


def test_the_observed_ceiling_is_gone():
    """Reproduces the actual failure. Every real finding had no stated award, and five
    of eight had no usable deadline either — so 60 points were unearnable and nothing
    could clear 42 however good the grant was.

    Under renormalisation an excellent opportunity on a terse page reaches the top of the
    scale, which is the true statement about it."""
    excellent_but_terse = ScoreParts(fit=57, award=None, timing=None)
    assert compose_score(excellent_but_terse) == 95

    old_ceiling = 100 * WEIGHTS["fit"] // 100  # fit alone, out of the full 100
    assert compose_score(excellent_but_terse) > old_ceiling


def test_fit_alone_still_orders_a_run_where_nothing_else_is_knowable():
    """The common case for this product: a whole week of funder pages that state
    neither an amount nor a deadline. The list still has to be ranked."""
    scores = [compose_score(ScoreParts(fit=f, award=None, timing=None))
              for f in (36, 28, 20, 8)]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == 4, "fit-only runs must not collapse into one value"


def test_components_are_clamped_but_null_survives():
    """A model that returns 99 for a 40-point component should be bounded, not trusted —
    but a null must never be quietly coerced to a number, in either direction."""
    assert compose_score(ScoreParts(fit=99, award=None, timing=None)) == 100
    assert compose_score(ScoreParts(fit=-5, award=None, timing=None)) == 0
    assert ScoreParts(fit=10, award=None, timing=None).missing == ["award", "timing"]
    assert ScoreParts(fit=10, award=0, timing=None).missing == ["timing"]


def test_a_renormalised_score_says_what_it_was_scored_on():
    """57 out of "fit and timing" and 57 out of all three are different claims. A number
    that quietly changed its denominator is worse than a low one."""
    note = basis_note(ScoreParts(fit=28, award=None, timing=9))
    assert "award" in note and "30 points" in note
    assert "no award amount" in note
    assert basis_note(ScoreParts(fit=28, award=20, timing=9)) == "", \
        "a fully-scored opportunity needs no caveat"


def test_the_schema_lets_the_model_say_it_does_not_know():
    """If award_score cannot be null in the schema, none of the above can happen — the
    model is forced to invent a number for evidence that is not on the page, which is
    the accuracy rule §6 exists to prevent."""
    schema = scoring_schema(["arts"])
    props = schema["properties"]
    assert props["award_score"]["type"] == ["integer", "null"]
    assert props["timing_score"]["type"] == ["integer", "null"]
    # Fit is always answerable — the page and the programs are both in front of it.
    assert props["fit_score"]["type"] == "integer"
    for field in ("fit_score", "award_score", "timing_score"):
        assert field in schema["required"]
    assert "score" not in props, "the total is composed here, never returned by the model"


def test_the_schema_stays_under_the_apis_union_limit():
    """A hard 400 from the structured-outputs API, and invisible until a live run.

    Adding the two nullable component scores took this schema to 17 union-typed
    parameters against a limit of 16, and every scoring call in the calibration run
    failed with "this causes exponential compilation cost". Nullability is a budget here;
    this is the test that says so before a run does.
    """
    from agent.score import MAX_UNION_PARAMS, union_param_count

    count = union_param_count(scoring_schema(["arts", "resilience"]))
    assert count <= MAX_UNION_PARAMS, (
        f"{count} union-typed parameters, limit {MAX_UNION_PARAMS}. Make one of them a "
        'plain type — "" reads as absent through `_gated` and fails `quote_on_page`.'
    )


# --- the prompt: whose nonprofit is this? -------------------------------------

def _cfg(**kw) -> Config:
    cfg = Config(programs=[ProgramCard(slug="arts", name="Arts", summary="Arts work")])
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_the_org_reaches_the_prompt():
    text = _preamble(_cfg(org_name="Rise Chicago", org_location="Chicago, Illinois"))
    assert "Rise Chicago" in text
    assert "Chicago, Illinois" in text


def test_no_region_is_invented_for_an_org_that_has_not_said():
    """An empty field is passed through as an empty field. A guessed region is the thing
    that broke this — fit is 40 points and every tenant was judged against San Diego."""
    text = _preamble(_cfg())
    assert "San Diego" not in text
    assert "Imperial" not in text
    assert "a nonprofit" in text
    assert "working in" not in text, "no region stated means no region claimed"


@pytest.mark.parametrize("hardcoded", ["San Diego", "Imperial County", "COO"])
def test_the_pilot_org_is_not_baked_into_anybody_elses_prompt(hardcoded):
    """The whole scoring prompt, not just the preamble. This is a multi-tenancy leak of
    the same kind as an unscoped SQL query — it just leaks into a judgement instead of
    into a result set."""
    cfg = _cfg(org_name="Rise Chicago", org_location="Chicago, Illinois")
    from agent.score import _SCORING_RULES, _TRIAGE_RULES

    whole = org_context(cfg) + _SCORING_RULES + _TRIAGE_RULES
    assert hardcoded not in whole


def test_the_prompt_does_not_tell_the_model_to_score_low():
    """"Be strict" sat in the SHARED preamble, so it biased the cheap triage filter as
    well as the score — pushing candidates out before anything could score them. The
    award floor already does that job deterministically, for free, before any model
    runs."""
    cfg = _cfg(org_name="Rise Chicago")
    from agent.score import _SCORING_RULES

    whole = (org_context(cfg) + _SCORING_RULES).casefold()
    assert "be strict" not in whole
    assert "use the low end" not in whole


def test_the_hours_cap_is_the_orgs_own():
    """10 of the 100 points are measured against it, and it was the constant 10 — one
    nonprofit's staffing applied to every tenant."""
    assert "40 collective team-hours" not in _preamble(_cfg())
    assert "about 40 collective" in _preamble(_cfg(max_effort_hours=40))
    assert "about 10 collective" in _preamble(_cfg())


def test_the_award_scale_has_anchors():
    """"Award size relative to the floor" with no scale defined resolves downward: is
    $25k against a $10k floor worth 15/35 or 30/35? The prompt never said."""
    from agent.score import _SCORING_RULES

    assert "at the floor" in _SCORING_RULES
    assert "three times the floor" in _SCORING_RULES
    assert "ten times the floor" in _SCORING_RULES


def test_the_effort_hours_estimate_is_anchored_to_requirements_not_award_size():
    """estimated_effort_hours used to have no scale at all — "estimate from the ask
    and the award size if the page is thin" invites anchoring the hours guess to a
    number (the award) that has nothing to do with how much paperwork an application
    takes. A $5,000 grant needing audited financials is more work than a $500,000
    grant needing a two-paragraph letter, and a scale with no anchors resolves toward
    whichever correlation is easiest to imagine, not the one that's actually true."""
    from agent.score import _SCORING_RULES

    assert "letter of interest" in _SCORING_RULES.lower()
    assert "audited financial" in _SCORING_RULES.lower()
    assert "board resolution" in _SCORING_RULES.lower()
    assert "the funder's size" in _SCORING_RULES or "the funder's reputation" in _SCORING_RULES


def test_award_score_ignores_a_past_grants_dollar_figure():
    """Found live, not by inspection: Hilton Foundation's real housing-priorities page
    describes a $2.4M grant already given to someone else in 2022 as a case study.
    Before this guardrail, a live scoring call read that figure as evidence of what a
    NEW applicant could receive and returned award_score=30/30 — full marks — on a
    page its own rationale correctly called "a past grant record" with "no open
    call." Re-run after the fix: award_score came back null, both times, and the
    total score corrected from 53 to 37 with nothing else about the page changed."""
    from agent.score import _SCORING_RULES

    assert "already disbursed" in _SCORING_RULES
    assert "not evidence of what YOU would receive" in _SCORING_RULES


def test_time_to_funds_days_defaults_to_null_not_a_guess():
    """The user's own complaint: this number reads as a fact and is usually a guess.
    Most funder pages state nothing about their internal review or disbursement
    timeline, so null has to be the DEFAULT the prompt reaches for, not an escape
    hatch for a hard case — otherwise "estimate from what the page says" quietly
    becomes "estimate from what grants usually take," which is not a fact about this
    funder at all."""
    from agent.score import _SCORING_RULES

    assert "null is the common, correct answer" in _SCORING_RULES.lower()
    assert "general knowledge" in _SCORING_RULES.lower()


# --- the metrics themselves ---------------------------------------------------

def test_spearman_handles_the_ties_a_compressed_run_produces():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # Every score identical: no information, which is 0 and emphatically not 1.
    assert spearman([5, 5, 5, 5], [1, 1, 0, 0]) == 0.0


def test_pair_accuracy_is_gentler_than_worst_yes_beats_best_no():
    assert pair_accuracy([90, 80], [20, 10]) == 1.0
    assert pair_accuracy([90, 15], [20, 10]) == 0.75   # one bad pair, not a total loss
    assert pair_accuracy([50], [50]) == 0.5            # a tie is half right


def test_spread_catches_a_band_held_open_by_one_outlier():
    """The real distribution. A 29-point band sounds healthy until you notice six of the
    eight scores sit inside seven points of each other and the range is being propped up
    by a single 13 at the bottom — which is why `band` alone cannot be the guard."""
    observed = spread([42, 42, 42, 38, 38, 35, 28, 13])
    assert observed.band == 29, "range looks healthy"
    assert observed.largest_cluster == 6, "and six of eight are one indistinguishable lump"
    assert observed.clustered_fraction == 0.75

    # A tenth of the scale is the window: closer than that and, to somebody choosing
    # which two grants to read on a Thursday, they are the same score.
    assert spread([91, 84, 76, 68, 61, 38, 24, 11]).largest_cluster == 2


def test_the_report_fails_the_distribution_that_started_this():
    """The end-to-end guard. Feed it the pre-fix numbers and it must object — the old
    harness asserted only that yeses outrank noes, which these satisfy."""
    pre_fix = report(yes_scores=[42, 42, 42, 38, 38], no_scores=[35, 28, 13])
    assert pre_fix.separation > 0, "the old assertion passed on this data"

    problems = " ".join(pre_fix.failures())
    assert "discrimination" in problems, "clustered scores must be reported"
    assert "headroom" in problems, "a 42-point ceiling must be reported"


def test_the_report_passes_a_healthy_distribution():
    healthy = report(yes_scores=[91, 84, 76, 68, 61], no_scores=[38, 24, 11])
    assert healthy.failures() == []
    assert healthy.pair_accuracy == 1.0, "every good/bad pair ordered correctly"
    # NOT > 0.9. The labels are binary, so Spearman is asked to reproduce ties the scores
    # do not have and cannot reach 1.0 however good the ordering is — ~0.85 IS the
    # ceiling for five yeses and three noes. See the note on Report.rank_agreement.
    assert healthy.rank_agreement > 0.8
