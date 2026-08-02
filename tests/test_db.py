"""The SQLite store: schema, CRUD, dedup, and the monthly purge.

Runs offline with no API key and no network. The three things worth actually testing
here are the ones that would fail silently in production:

  - the dedup probe, because a false negative means Mauri re-reads the same grant every
    Thursday and a false positive means a real opportunity never reaches her at all;
  - the purge boundary, because off-by-one means either the file grows forever or this
    month's findings get deleted the moment the month ticks over;
  - the reading order, because "human-check rows last" is something she asked for
    directly and it is easy to break from any of three different surfaces.

    .venv/bin/python -m pytest tests/test_db.py -q
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.models import DeadlineType, FunderType, Opportunity, Program, stable_id
from app import archive, repo
from app.db import DEFAULT_SETTINGS, init_db, month_key, session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A real database file per test — SQLite behaviour differs enough in :memory:
    (WAL, separate connections) that testing against a file is the honest choice."""
    path = tmp_path / "rise.db"
    monkeypatch.setenv("RISE_DB_PATH", str(path))
    monkeypatch.setenv("RISE_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)
    return path


def _opp(**kw) -> Opportunity:
    defaults = dict(
        id=kw.pop("id", None) or stable_id("https://example.invalid/a", "A grant"),
        title="A grant",
        funder="Example Foundation",
        award_min=10_000,
        award_max=50_000,
        deadline=date.today() + timedelta(days=60),
        estimated_effort_hours=8,
        program_match=[Program.ARTS],
        score=72,
        score_rationale="Clears the floor with runway to spare.",
        source_url="https://example.invalid/a",
        verified=True,
        needs_human_check=False,
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return Opportunity(**defaults)


# --- schema and seeds ---------------------------------------------------------

def test_init_is_idempotent(db):
    init_db(db)
    init_db(db)
    with session(db) as conn:
        assert len(repo.list_programs(conn)) == 7


def test_seeds_the_seven_programs_with_three_active(db):
    with session(db) as conn:
        programs = repo.list_programs(conn)
        active = [p["slug"] for p in programs if p["active"]]
    assert len(programs) == 7
    # The three Mauri named as priorities, and only those.
    assert sorted(active) == ["ARTS", "RESILIENCE", "RULFP"]


def test_the_other_four_programs_are_seeded_empty_not_invented(db):
    """We seed the four non-priority programs with a real name and a real URL and
    nothing else. Writing a description of a real organisation's programme that we
    never read is the same failure mode §6 forbids for award amounts."""
    with session(db) as conn:
        rest = [p for p in repo.list_programs(conn)
                if p["slug"] in {"ILIA", "RISE_NOW", "ON_THE_RISE", "NP_TRAININGS"}]
    assert len(rest) == 4
    for p in rest:
        assert p["source_url"].startswith("https://www.risesandiego.org/programs/")
        assert p["summary"] == ""
        assert p["keywords"] == []
        assert p["active"] is False


def test_seeds_funders_from_the_source_registry(db):
    with session(db) as conn:
        funders = repo.list_funders(conn)
    warm = [f for f in funders if f["warm"]]
    assert len(warm) == 8, "the eight partners from CLAUDE.md §7"
    assert all(f["sector"] for f in funders), "every funder carries a sector tag"


def test_award_floor_default_is_ten_thousand(db):
    """§11 Q1, answered. The placeholder is gone."""
    with session(db) as conn:
        assert repo.get_settings(conn)["min_award"] == 10_000
    assert DEFAULT_SETTINGS["min_award"] == "10000"


# --- settings -----------------------------------------------------------------

def test_settings_round_trip_with_types(db):
    with session(db) as conn:
        out = repo.update_settings(conn, {
            "min_award": "25000",
            "enabled": False,
            "sectors_active": ["government", "foundation"],
            "run_budget_usd": "0.50",
        })
    assert out["min_award"] == 25_000 and isinstance(out["min_award"], int)
    assert out["enabled"] is False
    assert out["sectors_active"] == ["government", "foundation"]
    assert out["run_budget_usd"] == 0.5


def test_unknown_settings_are_ignored_not_stored(db):
    with session(db) as conn:
        out = repo.update_settings(conn, {"drop_database": "yes please"})
        assert "drop_database" not in out
        rows = {r["key"] for r in conn.execute("SELECT key FROM settings")}
    assert "drop_database" not in rows


def test_corrupt_setting_falls_back_to_the_default(db):
    """A hand-edited or half-written cell should degrade, not take down a run."""
    with session(db) as conn:
        conn.execute("UPDATE settings SET value='not a number' WHERE key='min_award'")
    with session(db) as conn:
        assert repo.get_settings(conn)["min_award"] == 10_000


# --- programs -----------------------------------------------------------------

def test_program_crud(db):
    with session(db) as conn:
        created = repo.create_program(conn, {
            "name": "RISE Consult",
            "summary": "Advisory work.",
            "keywords": ["capacity building"],
            "active": True,
            "min_award": 5_000,
        })
        assert created["slug"] == "RISE_CONSULT"
        assert created["min_award"] == 5_000

        updated = repo.update_program(conn, created["id"],
                                      {"summary": "Edited by Mauri", "active": False})
        assert updated["summary"] == "Edited by Mauri"
        assert updated["active"] is False

        assert repo.delete_program(conn, created["id"]) is True
        assert repo.get_program(conn, created["id"]) is None


def test_duplicate_program_names_get_distinct_slugs(db):
    """Two cards with the same slug would silently collapse into one searched program."""
    with session(db) as conn:
        a = repo.create_program(conn, {"name": "RISE Arts"})
        b = repo.create_program(conn, {"name": "RISE Arts"})
    assert a["slug"] != b["slug"]


def test_program_needs_a_name(db):
    with session(db) as conn:
        with pytest.raises(ValueError):
            repo.create_program(conn, {"summary": "no name"})


# --- funders ------------------------------------------------------------------

def test_funder_deactivation_keeps_the_record(db):
    """The case that motivated the whole feature: a partner stops funding RISE. It
    leaves the search, but the relationship history stays."""
    with session(db) as conn:
        funders = repo.list_funders(conn)
        target = next(f for f in funders if f["warm"])
        repo.update_funder(conn, target["id"], {"active": False})

        assert repo.get_funder(conn, target["id"])["active"] is False
        assert target["id"] not in {f["id"] for f in repo.list_funders(conn, active_only=True)}
        assert target["id"] in {f["id"] for f in repo.list_funders(conn)}


def test_funder_create_is_idempotent_on_name(db):
    with session(db) as conn:
        first = repo.create_funder(conn, {"name": "New Partner Fund", "sector": "foundation"})
        again = repo.create_funder(conn, {"name": "new partner fund", "sector": "government"})
    assert first["id"] == again["id"], "same funder, not two rows"
    assert again["sector"] == "government", "the second write updates"


# --- opportunities, dedup, purge ----------------------------------------------

def test_save_and_read_back_every_new_attribute(db):
    """All eleven columns Mauri asked for survive a round trip."""
    opp = _opp(
        award_typical=35_000,
        deadline_type=DeadlineType.ROLLING,
        funder_type=FunderType.COMMUNITY,
        service_areas=["Arts", "Equity"],
        geography="San Diego and Imperial Counties",
        form_990_available=True,
        confidence_pct=68,
        contact_note="grants@example.invalid",
    )
    with session(db) as conn:
        repo.save_opportunity(conn, opp, run_id="run1")
        got = repo.list_opportunities(conn)[0]

    assert got["award_typical"] == 35_000
    assert got["deadline_type"] == "rolling"
    assert got["funder_type"] == "community"
    assert got["service_areas"] == ["Arts", "Equity"]
    assert got["geography"] == "San Diego and Imperial Counties"
    assert got["form_990_available"] is True
    assert got["confidence_pct"] == 68
    assert got["contact_note"] == "grants@example.invalid"
    assert got["found_on"] == date.today().isoformat()
    assert got["days_left"] == 60


def test_rerunning_updates_rather_than_duplicates(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(score=50), run_id="run1")
        repo.save_opportunity(conn, _opp(score=90), run_id="run2")
        rows = repo.list_opportunities(conn)
    assert len(rows) == 1
    assert rows[0]["score"] == 90


def test_dedup_probe_hits_and_misses(db):
    known = stable_id("https://example.invalid/a", "A grant")
    with session(db) as conn:
        assert archive.seen_this_month(conn, known) is False
        repo.save_opportunity(conn, _opp(), run_id="run1")
        assert archive.seen_this_month(conn, known) is True
        assert archive.seen_this_month(conn, "never-seen-id") is False


def test_dedup_is_scoped_to_the_month(db):
    """The documented exception: a grant seen last month is allowed to resurface."""
    known = stable_id("https://example.invalid/a", "A grant")
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1")
        conn.execute("UPDATE opportunities SET month_key='2020-01' WHERE id=?", (known,))
        assert archive.seen_this_month(conn, known) is False
        assert archive.seen_this_month(conn, known, month="2020-01") is True


def test_seen_ids_batch_matches_the_single_probe(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1")
        ids = archive.seen_ids_this_month(conn)
    assert ids == {stable_id("https://example.invalid/a", "A grant")}


def test_purge_deletes_earlier_months_and_keeps_this_one(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1")
        repo.save_opportunity(
            conn,
            _opp(id=stable_id("https://example.invalid/b", "Old grant"),
                 title="Old grant", source_url="https://example.invalid/b"),
            run_id="run0",
        )
        conn.execute("UPDATE opportunities SET month_key='2020-01' "
                     "WHERE source_url='https://example.invalid/b'")

    with session(db) as conn:
        removed = archive.purge_old_months(conn)
        remaining = repo.list_opportunities(conn)

    assert removed == 1
    assert len(remaining) == 1
    assert remaining[0]["month_key"] == month_key()


def test_purge_is_a_no_op_when_everything_is_current(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1")
    with session(db) as conn:
        assert archive.purge_old_months(conn) == 0
        assert len(repo.list_opportunities(conn)) == 1


# --- reading order ------------------------------------------------------------

def test_human_check_rows_sort_last(db):
    """Mauri asked for this explicitly: she wants to read everything the agent is sure
    about before anything it wants a second opinion on."""
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(
            id="needs-check", title="Ambiguous", source_url="https://example.invalid/x",
            score=99, needs_human_check=True), run_id="r")
        repo.save_opportunity(conn, _opp(
            id="clean-low", title="Clean but lower", source_url="https://example.invalid/y",
            score=20, needs_human_check=False), run_id="r")
        rows = repo.list_opportunities(conn)

    assert [r["id"] for r in rows] == ["clean-low", "needs-check"], \
        "a 99-scoring row that needs a human check still comes after a clean 20"


def test_scored_rows_outrank_amount_not_stated_within_a_block(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(
            id="no-amount", title="No amount", source_url="https://example.invalid/n",
            award_min=None, award_max=None, needs_human_check=True), run_id="r")
        repo.save_opportunity(conn, _opp(
            id="scored", title="Scored", source_url="https://example.invalid/s",
            score=10, needs_human_check=True), run_id="r")
        rows = repo.list_opportunities(conn)

    assert [r["id"] for r in rows] == ["scored", "no-amount"]


def test_month_summary_counts(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="r")
        summary = archive.month_summary(conn)
    assert summary["current_month"] == month_key()
    assert summary["months"][0]["total"] == 1
