"""The program cards must actually reach every search path. Offline, no key.

This file exists because of a defect the merge produced and no existing test caught:
`agent/apis.py` keyed its California category map and its Grants.gov vocabulary on the
old three-value `Program` enum. Once programs became editable cards, a program the user
ticked that was not one of the original three contributed nothing — and, worse, both
adapters then hit their "nothing matched, search everything" fallback. Their selection
silently did the opposite of what they asked for.

The tests below are all of the form "what they ticked is what gets searched", because
that is the invariant that broke.

    .venv/bin/python -m pytest tests/test_program_wiring.py -q
"""

from __future__ import annotations

from app.db import DEFAULT_ORG_ID

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

from agent.apis import CA_CATEGORIES, GG_SEED_KEYWORDS, program_vocabularies
from agent.config import Config, ProgramCard


def cfg_with(*cards: ProgramCard) -> Config:
    return Config(programs=list(cards))


DESCRIBED = ProgramCard(
    slug="RULFP", name="RISE Urban Leadership Fellows Program",
    keywords=["BIPOC leadership development", "cohort fellowship"],
    search_queries=["BIPOC leadership development grant San Diego"],
)
EMPTY = ProgramCard(slug="ILIA", name="Inclusive Leadership in Action (ILIA) Awards")


# --- the card's own state -----------------------------------------------------

def test_a_card_with_nothing_on_it_knows_it_is_empty():
    assert EMPTY.is_described is False
    assert DESCRIBED.is_described is True


def test_empty_card_supplies_no_search_terms():
    """The four non-priority programs ship this way on purpose. A programme's internal
    name is not what funders write, so inventing a query from it would spend money on
    noise and look like a working search."""
    assert EMPTY.api_vocabulary() is None


def test_a_tuned_default_beats_the_cards_own_queries():
    """search_queries are written for a general web search ("… grant San Diego") and
    over-narrow a federal index that has no notion of San Diego. Where we have a tuned
    vocabulary for a program, it wins."""
    assert DESCRIBED.api_vocabulary("community leadership development") == \
        "community leadership development"


def test_a_new_program_draws_vocabulary_from_its_own_card():
    """The point of editable cards: a program the user creates has no tuned default, so
    what they (or the assistant) wrote is what gets searched."""
    card = ProgramCard(slug="RISE_NOW", name="RISE Now",
                       keywords=["rapid response", "community organizing"])
    assert card.api_vocabulary(None) == "rapid response community organizing"


def test_vocabulary_is_capped_so_the_query_still_matches_something():
    card = ProgramCard(slug="X", name="X", keywords=[f"phrase{i}" for i in range(12)])
    assert len(card.api_vocabulary(None).split()) == 4


# --- what actually gets searched ----------------------------------------------

def test_ticked_programs_map_to_searches_and_empty_ones_are_reported():
    searchable, skipped = program_vocabularies(cfg_with(DESCRIBED, EMPTY))
    assert [slug for slug, _ in searchable] == ["RULFP"]
    assert skipped == ["ILIA"], "an empty card must be reported, not silently dropped"


def test_every_seeded_program_has_a_tuned_federal_vocabulary():
    for slug in ("RULFP", "RESILIENCE", "ARTS"):
        assert GG_SEED_KEYWORDS.get(slug), f"{slug} lost its federal vocabulary"


def test_a_program_beyond_the_original_three_is_searchable_once_described():
    """The exact regression. Before the fix, a described ILIA card contributed nothing
    to the federal search because the lookup was keyed on the Program enum."""
    described_ilia = ProgramCard(
        slug="ILIA", name="ILIA Awards",
        keywords=["diversity equity inclusion awards", "civic recognition"],
    )
    searchable, skipped = program_vocabularies(cfg_with(described_ilia))
    assert skipped == []
    assert searchable[0][0] == "ILIA"
    assert "diversity equity inclusion" in searchable[0][1]


def test_no_searches_at_all_when_every_ticked_card_is_empty():
    searchable, skipped = program_vocabularies(cfg_with(EMPTY))
    assert searchable == []
    assert skipped == ["ILIA"]


# --- California categories ----------------------------------------------------

def test_california_categories_are_keyed_by_slug_not_by_enum():
    """Keying on the enum is what made a seventh program invisible."""
    assert set(CA_CATEGORIES) == {"RULFP", "RESILIENCE", "ARTS"}
    assert all(isinstance(k, str) for k in CA_CATEGORIES)


def test_unticking_arts_removes_the_arts_category():
    mapped = {c for p in ["RULFP", "RESILIENCE"] if p in CA_CATEGORIES
              for c in CA_CATEGORIES[p]}
    assert "Libraries and Arts" not in mapped
    assert "Health & Human Services" in mapped


# --- the spend ceiling is theirs ----------------------------------------------

def test_the_run_budget_is_customizable_end_to_end(tmp_path, monkeypatch):
    """They set the ceiling on the dashboard; the pipeline must actually run to it.

    Three hops, each of which has silently broken before: settings row -> Config ->
    the Budget object that refuses the call. A default that looks right in the UI and
    is ignored by the run is worse than no control at all.
    """
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))

    from agent.config import load_from_db
    from agent.score import Budget, BudgetExceeded
    from app.db import init_db, session
    from app.repo import get_settings, update_settings

    init_db()
    seed_starter_funders()
    seed_starter_programs()
    with session() as conn:
        assert get_settings(conn, org_id=DEFAULT_ORG_ID)["run_budget_usd"] == 1.00
        update_settings(conn, {"run_budget_usd": 0.25}, org_id=DEFAULT_ORG_ID)

    cfg = load_from_db()
    assert cfg.weekly_budget_usd == 0.25

    budget = Budget(ceiling_usd=cfg.weekly_budget_usd)
    budget.check("claude-sonnet-4-6", 1_000, 500)          # well under — fine
    with pytest.raises(BudgetExceeded):
        budget.check("claude-sonnet-4-6", 10_000_000, 1)   # over their ceiling — refused


# --- the COO's ranking criteria (§11 Q5, answered) ----------------------------

def test_the_scoring_prompt_carries_her_weights_and_nothing_else():
    """The weights, asserted against the thing that now enforces them.

    This used to grep the prompt for the literal strings "40  program fit" and so on,
    which is all it could do while the weights existed only as English inside the prompt
    and the model returned one holistic total. That is the arrangement that let a rubric
    spend 60 of its 100 points on evidence most funder pages do not carry without
    anything in the suite noticing.

    `WEIGHTS` is the source of truth now and `compose_score` applies it, so the check is
    that the prompt asks for the three components the composer expects — a name drifting
    apart from its weight is the failure worth catching, not a changed adjective.
    """
    from agent.score import WEIGHTS, _SCORING_RULES

    assert WEIGHTS == {"fit": 40, "award": 35, "timing": 25}
    assert sum(WEIGHTS.values()) == 100

    # Matched on the pair, not on the alignment: the components are padded into a column
    # and a whitespace change is not a regression.
    for component, weight in (("fit_score", 40), ("award_score", 35),
                              ("timing_score", 25)):
        assert re.search(rf"{component}\s*,?\s+0-{weight}\b", _SCORING_RULES), \
            f"the prompt does not ask for {component} out of {weight}"

    assert "funder warmth" not in _SCORING_RULES.lower() or \
        "Funder warmth is gone" in _SCORING_RULES


def test_warmth_no_longer_buys_a_candidate_the_scoring_budget():
    """`warm` used to lead the spend-ordering tuple, so the organization's existing relationships
    consumed the budget first — which is precisely the funders the stakeholder says they
    do not want. Ordering must now depend only on the opportunity."""
    from agent.run import _rank_for_scoring
    from agent.parse import ParsedPage
    from agent.sources import Confidence, Source, Tier

    def page(url, amount):
        p = ParsedPage(url=url, title="t", text="x" * 2000)
        p.amounts = [type("E", (), {"value": amount, "snippet": "", "kind": "amount"})()]
        return p

    def src(name, warm):
        return Source(name=name, funder=name, url=f"https://{name}.invalid",
                      tier=Tier.WARM, confidence=Confidence.CONFIRMED, warm=warm)

    warm_small = (page("https://a.invalid", 10_000), src("warm", True))
    cold_big = (page("https://b.invalid", 500_000), src("cold", False))

    ranked = _rank_for_scoring([warm_small, cold_big], Config())
    assert ranked[0][1].funder == "cold", \
        "the bigger award must be scored first regardless of the relationship"


def test_both_time_criteria_are_in_the_response_schema():
    from agent.score import scoring_schema

    props = scoring_schema(["ARTS"])["properties"]
    assert "application_lead_time_days" in props, "calendar time to be ready to submit"
    assert "time_to_funds_days" in props, "submit -> money in the bank"
    required = scoring_schema(["ARTS"])["required"]
    assert "application_lead_time_days" in required
    assert "time_to_funds_days" in required


def test_absurd_day_counts_are_discarded_rather_than_shown():
    from agent.score import _bounded

    assert _bounded(21, 400) == 21
    assert _bounded(99999, 400) is None, "a wrong number must not render as fact"
    assert _bounded(-5, 400) is None
    assert _bounded(None, 400) is None
    assert _bounded("not a number", 400) is None


# --- effort estimate is mandatory --------------------------------------------
#
# CLAUDE.md weights effort against a hard 10-hour cap, and §1 is explicit that the
# cap is the decision the whole product exists to serve. A null cannot be compared
# against 10, so an opportunity without an estimate silently drops out of that
# comparison instead of failing it. These tests keep the field non-nullable: it is an
# inferred judgement, not a claim about the page, so nothing in §6 requires withholding
# it when the page is thin.

def test_effort_hours_is_required_and_not_nullable():
    from agent.score import scoring_schema

    schema = scoring_schema(["RULFP", "ARTS"])
    effort = schema["properties"]["estimated_effort_hours"]

    assert effort["type"] == "integer", "a nullable effort estimate is unusable against the 10-hour cap"
    assert "estimated_effort_hours" in schema["required"]


def test_sourced_fields_stay_nullable():
    """The opposite rule, asserted so the change above cannot be widened by accident.

    Award amounts and deadlines must stay nullable — CLAUDE.md forbids inventing
    them. Only the inferred estimate is mandatory.
    """
    from agent.score import scoring_schema

    props = scoring_schema(["RULFP"])["properties"]
    for field in ("award_min_stated", "award_max_stated", "deadline_stated"):
        assert "null" in props[field]["type"], f"{field} must stay nullable — §6"


# --- per-stage model choice ----------------------------------------------------

def test_every_offered_model_has_a_price():
    """The one that turns a UI mistake into a dead run.

    `Budget.check` does a dict lookup on PRICING before every call. A model in the
    picker with no entry does not produce a mis-priced run — it raises KeyError on the
    first candidate and the whole search fails.
    """
    from agent.score import MODEL_CHOICES, PRICING

    for stage, choices in MODEL_CHOICES.items():
        for choice in choices:
            assert choice["id"] in PRICING, (
                f"step {stage} offers {choice['id']} and nothing knows what it costs"
            )


def test_each_stage_recommends_exactly_one_model():
    from agent.score import MODEL_CHOICES

    for stage, choices in MODEL_CHOICES.items():
        recommended = [c for c in choices if c.get("recommended")]
        assert len(recommended) == 1, f"step {stage} recommends {len(recommended)}"


def test_the_defaults_are_the_recommended_choices():
    """Otherwise the picker chips one option and the pipeline quietly runs another."""
    from agent.score import MODEL_CHOICES, SCORING_MODEL, TRIAGE_MODEL

    assert next(c["id"] for c in MODEL_CHOICES[2] if c.get("recommended")) == TRIAGE_MODEL
    assert next(c["id"] for c in MODEL_CHOICES[3] if c.get("recommended")) == SCORING_MODEL


def test_a_bare_model_name_is_still_priced():
    """The `provider:` prefix arrived with per-stage choice. Anything still passing a
    bare name — a script, the CLI — must degrade rather than abort a run."""
    from agent.score import PRICING, price_for

    assert price_for("claude-sonnet-4-6") == PRICING["anthropic:claude-sonnet-4-6"]
    assert price_for("anthropic:claude-sonnet-4-6") == PRICING["anthropic:claude-sonnet-4-6"]


def test_a_model_nobody_priced_still_raises():
    """Guessing a price would put a wrong number under somebody's spend limit."""
    import pytest as _pytest

    from agent.score import price_for

    with _pytest.raises(KeyError):
        price_for("anthropic:claude-imaginary-9")


def test_an_unknown_stored_model_falls_back_instead_of_killing_the_run(tmp_path, monkeypatch):
    """A settings row written by an older build, or by hand, must not be able to abort
    every future search."""
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))

    from agent.config import load_from_db
    from agent.score import SCORING_MODEL
    from app.db import DEFAULT_ORG_ID, init_db, session
    from app import repo

    init_db()
    with session() as conn:
        conn.execute(
            "INSERT INTO settings(org_id, key, value, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(org_id, key) DO UPDATE SET value=excluded.value",
            (DEFAULT_ORG_ID, "scoring_model", "anthropic:claude-from-the-future",
             "2026-01-01"))

    cfg = load_from_db(org_id=DEFAULT_ORG_ID)
    assert cfg.scoring_model == SCORING_MODEL, "an unusable setting must not be obeyed"


# --- live spend during a run ---------------------------------------------------

def test_the_budget_emits_a_running_total(caplog):
    """`usd_spent` is otherwise only written when a run finishes, so the status strip
    read $0.0000 for ten minutes and then jumped — on the one number §8 asks the user to
    trust."""
    import logging

    from agent.score import SPEND_MARKER, Budget

    budget = Budget(ceiling_usd=1.0)
    with caplog.at_level(logging.INFO, logger="agent.score"):
        budget.record("anthropic:claude-haiku-4-5", 10_000, 1_000)
        budget.record("anthropic:claude-haiku-4-5", 10_000, 1_000)

    markers = [r.getMessage() for r in caplog.records if SPEND_MARKER.strip() in r.getMessage()]
    assert len(markers) == 2, "one running total per call"
    # Cumulative, not per-call: the strip shows spend-so-far.
    totals = [float(m.split()[-1]) for m in markers]
    assert totals[1] > totals[0]
    assert abs(totals[-1] - budget.spent_usd) < 1e-9


def test_the_runner_reads_the_marker_and_ignores_everything_else():
    from app.runner import _spend_from

    assert _spend_from("::spend 0.041234") == pytest.approx(0.041234)
    assert _spend_from("INFO:agent.score:::spend 1.5") == pytest.approx(1.5)
    assert _spend_from("  scored  84  The Parker Foundation") is None
    assert _spend_from("") is None


def test_a_malformed_marker_does_not_take_down_the_output_thread():
    """`_pump` is the only thing draining the child's stdout. An exception there stalls
    the pipe and the search hangs, so a cosmetic parse must never raise."""
    from app.runner import _spend_from

    for junk in ("::spend", "::spend abc", "::spend  ", "::spend NaNsense"):
        assert _spend_from(junk) is None or isinstance(_spend_from(junk), float)


# --- the live funnel behind the three stage boxes -------------------------------

def test_the_pipeline_emits_the_funnel_as_it_moves(caplog):
    """The boxes on This week are the run now, not a summary printed after it. That only
    works if the counters leave the child while it is still working."""
    import json
    import logging

    from agent.models import RunLog
    from agent.run import _emit_funnel
    from agent.score import STAGE_MARKER

    run = RunLog(started_at=datetime.now(timezone.utc))
    with caplog.at_level(logging.INFO, logger="rise"):
        run.candidates_parsed = 214
        _emit_funnel(run, survivors=61)
        run.triaged, run.scored = 61, 23
        _emit_funnel(run, survivors=61, kept=6)

    markers = [r.getMessage() for r in caplog.records if STAGE_MARKER.strip() in r.getMessage()]
    assert len(markers) == 2
    first, last = (json.loads(m.split(STAGE_MARKER.strip(), 1)[1]) for m in markers)
    assert first == {"parsed": 214, "triaged": 0, "scored": 0, "survivors": 61}
    # The two denominators only appear once there is something to divide by — a count
    # with nothing to divide by cannot fill a bar.
    assert last == {"parsed": 214, "triaged": 61, "scored": 23,
                    "survivors": 61, "kept": 6}


def test_the_runner_reads_the_funnel_and_survives_a_broken_one():
    """Same contract as the spend marker: this drives three progress bars, so a bad line
    costs a frame of animation and never the thread draining the child's output."""
    from app.runner import _funnel_from

    assert _funnel_from('::stage {"parsed":214,"triaged":61}') == {"parsed": 214, "triaged": 61}
    assert _funnel_from('INFO:rise:::stage {"parsed":1}') == {"parsed": 1}
    assert _funnel_from("  ✓ The Parker Foundation") is None
    # Anything that is not a JSON object is dropped rather than written to the run row,
    # where it would land in `progress` and be read back as a funnel.
    for junk in ("::stage", "::stage {", "::stage []", "::stage 7", "::stage null"):
        assert _funnel_from(junk) is None
