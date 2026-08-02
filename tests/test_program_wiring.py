"""The program cards must actually reach every search path. Offline, no key.

This file exists because of a defect the merge produced and no existing test caught:
`agent/apis.py` keyed its California category map and its Grants.gov vocabulary on the
old three-value `Program` enum. Once programs became editable cards, a program Mauri
ticked that was not one of the original three contributed nothing — and, worse, both
adapters then hit their "nothing matched, search everything" fallback. Her selection
silently did the opposite of what she asked for.

The tests below are all of the form "what she ticked is what gets searched", because
that is the invariant that broke.

    .venv/bin/python -m pytest tests/test_program_wiring.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    """The point of editable cards: a program Mauri creates has no tuned default, so
    what she (or the assistant) wrote is what gets searched."""
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


# --- the spend ceiling is hers ------------------------------------------------

def test_the_run_budget_is_customizable_end_to_end(tmp_path, monkeypatch):
    """She sets the ceiling on the dashboard; the pipeline must actually run to it.

    Three hops, each of which has silently broken before: settings row -> Config ->
    the Budget object that refuses the call. A default that looks right in the UI and
    is ignored by the run is worse than no control at all.
    """
    monkeypatch.setenv("RISE_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("RISE_KEYFILE", str(tmp_path / ".fernet-key"))

    from agent.config import load_from_db
    from agent.score import Budget, BudgetExceeded
    from app.db import init_db, session
    from app.repo import get_settings, update_settings

    init_db()
    with session() as conn:
        assert get_settings(conn)["run_budget_usd"] == 1.00
        update_settings(conn, {"run_budget_usd": 0.25})

    cfg = load_from_db()
    assert cfg.weekly_budget_usd == 0.25

    budget = Budget(ceiling_usd=cfg.weekly_budget_usd)
    budget.check("claude-sonnet-4-6", 1_000, 500)          # well under — fine
    with pytest.raises(BudgetExceeded):
        budget.check("claude-sonnet-4-6", 10_000_000, 1)   # over her ceiling — refused


# --- effort estimate is mandatory --------------------------------------------
#
# CLAUDE.md §7 weights effort against a hard 10-hour cap, and §1 is explicit that the
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

    Award amounts and deadlines must stay nullable — CLAUDE.md §6 forbids inventing
    them. Only the inferred estimate is mandatory.
    """
    from agent.score import scoring_schema

    props = scoring_schema(["RULFP"])["properties"]
    for field in ("award_min_stated", "award_max_stated", "deadline_stated"):
        assert "null" in props[field]["type"], f"{field} must stay nullable — §6"
