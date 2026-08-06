"""The SQLite store: schema, CRUD, dedup, and the monthly purge.

Runs offline with no API key and no network. The three things worth actually testing
here are the ones that would fail silently in production:

  - the dedup probe, because a false negative means the user re-reads the same grant every
    Thursday and a false positive means a real opportunity never reaches them at all;
  - the purge boundary, because off-by-one means either the file grows forever or this
    month's findings get deleted the moment the month ticks over;
  - the reading order, because "human-check rows last" is something they asked for
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

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

from agent.models import DeadlineType, FunderType, Opportunity, Program, stable_id
from app import archive, repo
from app.db import DEFAULT_ORG_ID, DEFAULT_SETTINGS, init_db, month_key, session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A real database file per test — SQLite behaviour differs enough in :memory:
    (WAL, separate connections) that testing against a file is the honest choice."""
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)
    seed_starter_funders(path)
    seed_starter_programs(path)
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
        assert len(repo.list_programs(conn, org_id=DEFAULT_ORG_ID)) == 7


def test_seeds_the_seven_programs_with_three_active(db):
    with session(db) as conn:
        programs = repo.list_programs(conn, org_id=DEFAULT_ORG_ID)
        active = [p["slug"] for p in programs if p["active"]]
    assert len(programs) == 7
    # The three the user named as priorities, and only those.
    assert sorted(active) == ["ARTS", "RESILIENCE", "RULFP"]


def test_the_other_four_programs_are_seeded_empty_not_invented(db):
    """We seed the four non-priority programs with a real name and a real URL and
    nothing else. Writing a description of a real organisation's programme that we
    never read is the same failure mode §6 forbids for award amounts."""
    with session(db) as conn:
        rest = [p for p in repo.list_programs(conn, org_id=DEFAULT_ORG_ID)
                if p["slug"] in {"ILIA", "RISE_NOW", "ON_THE_RISE", "NP_TRAININGS"}]
    assert len(rest) == 4
    for p in rest:
        assert p["source_url"].startswith("https://www.risesandiego.org/programs/")
        assert p["summary"] == ""
        assert p["keywords"] == []
        assert p["active"] is False


def test_seeds_funders_from_the_source_registry(db):
    with session(db) as conn:
        funders = repo.list_funders(conn, org_id=DEFAULT_ORG_ID)
    assert len(funders) >= 8
    assert all(f["sector"] for f in funders), "every funder carries a sector tag"


def test_a_seeded_org_is_told_it_has_no_relationships_with_anybody(db):
    """`Source.warm` is the pilot's fact about the pilot, and it is not transitive.

    Importing it verbatim put "Existing relationship" on eight funders in the list of a
    nonprofit that had signed up ten minutes earlier — an assertion about their
    organisation that nobody at their organisation had made. Whether a relationship
    exists is theirs to state, on the funder editor, and it starts unstated.
    """
    with session(db) as conn:
        funders = repo.list_funders(conn, org_id=DEFAULT_ORG_ID)

    assert not [f for f in funders if f["warm"]], "nobody's warmth but their own"
    assert not [f for f in funders if f["sector"] == "warm_partner"], (
        "sector_for() reads warmth, so it has to be derived from the cold copy too — "
        "otherwise the chip goes but the 'Partners we already work with' heading stays"
    )


def test_award_floor_default_is_ten_thousand(db):
    """§11 Q1, answered. The placeholder is gone."""
    with session(db) as conn:
        assert repo.get_settings(conn, org_id=DEFAULT_ORG_ID)["min_award"] == 10_000
    assert DEFAULT_SETTINGS["min_award"] == "10000"


# --- settings -----------------------------------------------------------------

def test_settings_round_trip_with_types(db):
    with session(db) as conn:
        out = repo.update_settings(conn, {
            "min_award": "25000",
            "enabled": False,
            "sectors_active": ["government", "foundation"],
            "run_budget_usd": "0.50",
        }, org_id=DEFAULT_ORG_ID)
    assert out["min_award"] == 25_000 and isinstance(out["min_award"], int)
    assert out["enabled"] is False
    assert out["sectors_active"] == ["government", "foundation"]
    assert out["run_budget_usd"] == 0.5


def test_unknown_settings_are_ignored_not_stored(db):
    with session(db) as conn:
        out = repo.update_settings(conn, {"drop_database": "yes please"}, org_id=DEFAULT_ORG_ID)
        assert "drop_database" not in out
        rows = {r["key"] for r in conn.execute("SELECT key FROM settings")}
    assert "drop_database" not in rows


def test_corrupt_setting_falls_back_to_the_default(db):
    """A hand-edited or half-written cell should degrade, not take down a run."""
    with session(db) as conn:
        conn.execute("UPDATE settings SET value='not a number' WHERE key='min_award'")
    with session(db) as conn:
        assert repo.get_settings(conn, org_id=DEFAULT_ORG_ID)["min_award"] == 10_000


# --- programs -----------------------------------------------------------------

def test_program_crud(db):
    with session(db) as conn:
        created = repo.create_program(conn, {
            "name": "RISE Consult",
            "summary": "Advisory work.",
            "keywords": ["capacity building"],
            "active": True,
            "min_award": 5_000,
        }, org_id=DEFAULT_ORG_ID)
        assert created["slug"] == "RISE_CONSULT"
        assert created["min_award"] == 5_000

        updated = repo.update_program(conn, created["id"],
                                      {"summary": "Edited by the user", "active": False}, org_id=DEFAULT_ORG_ID)
        assert updated["summary"] == "Edited by the user"
        assert updated["active"] is False

        assert repo.delete_program(conn, created["id"], org_id=DEFAULT_ORG_ID) is True
        assert repo.get_program(conn, created["id"], org_id=DEFAULT_ORG_ID) is None


def test_duplicate_program_names_get_distinct_slugs(db):
    """Two cards with the same slug would silently collapse into one searched program."""
    with session(db) as conn:
        a = repo.create_program(conn, {"name": "RISE Arts"}, org_id=DEFAULT_ORG_ID)
        b = repo.create_program(conn, {"name": "RISE Arts"}, org_id=DEFAULT_ORG_ID)
    assert a["slug"] != b["slug"]


def test_program_needs_a_name(db):
    with session(db) as conn:
        with pytest.raises(ValueError):
            repo.create_program(conn, {"summary": "no name"}, org_id=DEFAULT_ORG_ID)


# --- funders ------------------------------------------------------------------

def test_funder_deactivation_keeps_the_record(db):
    """The case that motivated the whole feature: a partner stops funding the organization. It
    leaves the search, but the relationship history stays."""
    with session(db) as conn:
        funders = repo.list_funders(conn, org_id=DEFAULT_ORG_ID)
        # Marked warm here rather than found warm: an org states its own relationships,
        # so the seed no longer arrives with any. Deactivating one is the same act
        # either way — this is the funder they said they already receive money from.
        target = funders[0]
        repo.update_funder(conn, target["id"], {"warm": True}, org_id=DEFAULT_ORG_ID)
        repo.update_funder(conn, target["id"], {"active": False}, org_id=DEFAULT_ORG_ID)
        assert repo.get_funder(conn, target["id"], org_id=DEFAULT_ORG_ID)["warm"] is True

        assert repo.get_funder(conn, target["id"], org_id=DEFAULT_ORG_ID)["active"] is False
        assert target["id"] not in {f["id"] for f in repo.list_funders(conn, active_only=True, org_id=DEFAULT_ORG_ID)}
        assert target["id"] in {f["id"] for f in repo.list_funders(conn, org_id=DEFAULT_ORG_ID)}


def test_funder_create_is_idempotent_on_name(db):
    with session(db) as conn:
        first = repo.create_funder(conn, {"name": "New Partner Fund", "sector": "foundation"}, org_id=DEFAULT_ORG_ID)
        again = repo.create_funder(conn, {"name": "new partner fund", "sector": "government"}, org_id=DEFAULT_ORG_ID)
    assert first["id"] == again["id"], "same funder, not two rows"
    assert again["sector"] == "government", "the second write updates"


# --- opportunities, dedup, purge ----------------------------------------------

def test_save_and_read_back_every_new_attribute(db):
    """All eleven columns the user asked for survive a round trip."""
    opp = _opp(
        award_typical=35_000,
        deadline_type=DeadlineType.ROLLING,
        funder_type=FunderType.COMMUNITY,
        service_areas=["Arts", "Equity"],
        geography="San Diego and Imperial Counties",
        confidence_pct=68,
        contact_note="grants@example.invalid",
    )
    with session(db) as conn:
        repo.save_opportunity(conn, opp, run_id="run1", org_id=DEFAULT_ORG_ID)
        got = repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)[0]

    assert got["award_typical"] == 35_000
    assert got["deadline_type"] == "rolling"
    assert got["funder_type"] == "community"
    assert got["service_areas"] == ["Arts", "Equity"]
    assert got["geography"] == "San Diego and Imperial Counties"
    assert got["confidence_pct"] == 68
    assert got["contact_note"] == "grants@example.invalid"
    assert got["found_on"] == date.today().isoformat()
    assert got["days_left"] == 60


def test_rerunning_updates_rather_than_duplicates(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(score=50), run_id="run1", org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(conn, _opp(score=90), run_id="run2", org_id=DEFAULT_ORG_ID)
        rows = repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)
    assert len(rows) == 1
    assert rows[0]["score"] == 90


def test_dedup_probe_hits_and_misses(db):
    known = stable_id("https://example.invalid/a", "A grant")
    with session(db) as conn:
        assert archive.seen_this_month(conn, known, org_id=DEFAULT_ORG_ID) is False
        repo.save_opportunity(conn, _opp(), run_id="run1", org_id=DEFAULT_ORG_ID)
        assert archive.seen_this_month(conn, known, org_id=DEFAULT_ORG_ID) is True
        assert archive.seen_this_month(conn, "never-seen-id", org_id=DEFAULT_ORG_ID) is False


def test_dedup_is_scoped_to_the_month(db):
    """The documented exception: a grant seen last month is allowed to resurface."""
    known = stable_id("https://example.invalid/a", "A grant")
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1", org_id=DEFAULT_ORG_ID)
        conn.execute("UPDATE opportunities SET month_key='2020-01' WHERE id=?", (known,))
        assert archive.seen_this_month(conn, known, org_id=DEFAULT_ORG_ID) is False
        assert archive.seen_this_month(conn, known, month="2020-01", org_id=DEFAULT_ORG_ID) is True


def test_seen_ids_batch_matches_the_single_probe(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1", org_id=DEFAULT_ORG_ID)
        ids = archive.seen_ids_this_month(conn, org_id=DEFAULT_ORG_ID)
    assert ids == {stable_id("https://example.invalid/a", "A grant")}


def test_purge_deletes_earlier_months_and_keeps_this_one(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1", org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(
            conn,
            _opp(id=stable_id("https://example.invalid/b", "Old grant"),
                 title="Old grant", source_url="https://example.invalid/b"),
            run_id="run0",
        org_id=DEFAULT_ORG_ID)
        conn.execute("UPDATE opportunities SET month_key='2020-01' "
                     "WHERE source_url='https://example.invalid/b'")

    with session(db) as conn:
        removed = archive.purge_old_months(conn, org_id=DEFAULT_ORG_ID)
        remaining = repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)

    assert removed == 1
    assert len(remaining) == 1
    assert remaining[0]["month_key"] == month_key()


def test_purge_is_a_no_op_when_everything_is_current(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="run1", org_id=DEFAULT_ORG_ID)
    with session(db) as conn:
        assert archive.purge_old_months(conn, org_id=DEFAULT_ORG_ID) == 0
        assert len(repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)) == 1


# --- reading order ------------------------------------------------------------

def test_human_check_rows_sort_last(db):
    """the user asked for this explicitly: they want to read everything the agent is sure
    about before anything it wants a second opinion on."""
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(
            id="needs-check", title="Ambiguous", source_url="https://example.invalid/x",
            score=99, needs_human_check=True), run_id="r", org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(conn, _opp(
            id="clean-low", title="Clean but lower", source_url="https://example.invalid/y",
            score=20, needs_human_check=False), run_id="r", org_id=DEFAULT_ORG_ID)
        rows = repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)

    assert [r["id"] for r in rows] == ["clean-low", "needs-check"], \
        "a 99-scoring row that needs a human check still comes after a clean 20"


def test_a_stated_award_amount_does_not_outrank_a_better_score(db):
    """The ranking bug, exactly as it appeared in the last real run.

    The order used to put rows with a sourced award amount above rows without one.
    That was right when "no amount" meant "we never paid to score it". Sonnet now
    scores every candidate, so the rule had quietly become "rank by whether the funder
    happened to publish a number" — and a score-18 opportunity sat above a score-65
    because the 18 had a figure on its page.
    """
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(
            id="low-but-has-amount", title="Prebys Rooted and Rising",
            source_url="https://example.invalid/prebys",
            award_max=150_000, score=18), run_id="r", org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(conn, _opp(
            id="high-no-amount", title="City of SD — Apply for Funding",
            source_url="https://example.invalid/sd",
            award_min=None, award_max=None, score=65), run_id="r", org_id=DEFAULT_ORG_ID)
        rows = repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)

    assert [r["id"] for r in rows] == ["high-no-amount", "low-but-has-amount"], \
        "score must decide the order, not whether an amount happened to be published"


def test_a_missing_amount_is_no_longer_a_human_check(db):
    """Most funders never publish an amount — the flag fired on 5 of 5 results in the
    last real run, which made it useless as a signal and emptied the 'clean' section.
    It now means one thing: a claim we could not verify against the page."""
    opp = _opp(award_min=None, award_max=None, deadline=None, needs_human_check=False)
    assert opp.needs_human_check is False

    with session(db) as conn:
        repo.save_opportunity(conn, opp, run_id="r", org_id=DEFAULT_ORG_ID)
        assert repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)[0]["needs_human_check"] is False


def test_month_summary_counts(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="r", org_id=DEFAULT_ORG_ID)
        summary = archive.month_summary(conn, org_id=DEFAULT_ORG_ID)
    assert summary["current_month"] == month_key()
    assert summary["months"][0]["total"] == 1


# --- regression: two registry entries sharing a funder name -------------------
#
# Grants.gov and SAM.gov are both funder="U.S. Federal Government" in sources.py.
# Hashing the seed id on name alone collapsed them into a single row, so SAM.gov
# disappeared from the registry with no error anywhere — the seed overwrote itself.
# Found while merging the indexed-source branch.

def test_sources_sharing_a_funder_name_get_separate_rows(db):
    from agent.sources import ALL_SOURCES

    from app.db import REMOVE_LIST_SEED

    with session(db) as conn:
        seeded = repo.list_funders(conn, org_id=DEFAULT_ORG_ID)

    # The table also holds remove-list-only rows — entries that are not crawl sources,
    # like the County Equity Impact Grant, which is a PROGRAMME rather than a funder.
    extra = sum(1 for n in REMOVE_LIST_SEED
                if n.casefold() not in {s.funder.casefold() for s in ALL_SOURCES})
    assert len(seeded) == len(ALL_SOURCES) + extra, (
        f"{len(ALL_SOURCES)} registry entries + {extra} remove-list-only seeded "
        f"{len(seeded)} rows — something collapsed or duplicated"
    )
    federal = [f for f in seeded if f["name"] == "U.S. Federal Government"]
    assert len(federal) == 2, "Grants.gov and SAM.gov must both survive seeding"
    assert {f["adapter"] for f in federal} == {"grants_gov", None}


def test_indexed_adapters_survive_the_round_trip(db):
    """A source that loses its adapter stops being read as an API and silently
    becomes an ordinary web page — a whole class of funding disappearing quietly."""
    from agent.sources import Tier, sources_from_db

    fetchable, _ = sources_from_db(
        Tier.GOVERNMENT, ["warm_partner", "foundation", "government", "arts_agency"])
    apis = sorted(s.adapter for s in fetchable if s.is_api)
    assert apis == ["ca_grants_portal", "grants_gov"]


def test_sector_no_longer_narrows_the_funder_list(db):
    """R8 removed the sector filter, and this used to assert the opposite.

    It was an invisible exclusion on a taxonomy we invented: four buckets, assigned by
    `sector_for` or defaulted to "foundation" for anything typed in, silently dropping
    funders in the free tier where nothing explains itself. Same reasoning as the
    geography filter in agent/filters.py, and the same fix — removed rather than
    repaired. Which funders get searched is the funder list, one decision at a time.

    The argument stays in the signature so old callers still work; it is ignored.
    """
    from agent.sources import Tier, sources_from_db

    everything, _ = sources_from_db(Tier.GOVERNMENT, [])
    one_sector, _ = sources_from_db(Tier.GOVERNMENT, ["warm_partner"])

    assert [s.funder for s in one_sector] == [s.funder for s in everything], \
        "a ticked sector still narrows the search, invisibly"
    assert any(s.is_api for s in one_sector), \
        "the indexed databases were dropped by a filter that should be gone"


def test_credit_never_lands_on_an_unchecked_source():
    """Grants.gov and SAM.gov share funder="U.S. Federal Government"; SAM.gov is
    NOT_CHECKED. Crediting by name alone reported the federal source as unchecked
    while displaying the twelve grants it had just returned."""
    from agent.models import RunLog, SourceHealth, SourceStatus

    run = RunLog(started_at=datetime.now(timezone.utc))
    run.record(SourceHealth(name="SAM.gov", funder="U.S. Federal Government",
                            status=SourceStatus.NOT_CHECKED))
    run.record(SourceHealth(name="Grants.gov", funder="U.S. Federal Government",
                            status=SourceStatus.OK))
    run.credit("U.S. Federal Government", 12)

    unchecked = next(h for h in run.source_health if h.name == "SAM.gov")
    checked = next(h for h in run.source_health if h.name == "Grants.gov")
    assert unchecked.candidates == 0, "an unchecked source cannot have produced results"
    assert checked.candidates == 12


def test_source_kind_survives_the_sink(db):
    """Provenance was being dropped on the way into the database, so every record read
    back as a funder page regardless of where it came from — and the dashboard could
    not tell the user which results came from a public database rather than a partner."""
    from agent.models import SourceKind

    with session(db) as conn:
        repo.save_opportunity(conn, _opp(
            id="from-db", title="A state grant",
            source_url="https://example.invalid/state",
            source_kind=SourceKind.INDEXED_DATABASE), run_id="r", org_id=DEFAULT_ORG_ID)
        repo.save_opportunity(conn, _opp(source_kind=SourceKind.FUNDER_PAGE), run_id="r", org_id=DEFAULT_ORG_ID)
        rows = {o["id"]: o for o in repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)}

    assert rows["from-db"]["source_kind"] == "indexed_database"
    assert rows[stable_id("https://example.invalid/a", "A grant")]["source_kind"] \
        == "funder_page"


def test_sqlite_sink_creates_its_own_schema(tmp_path, monkeypatch):
    """The sink is the last thing a multi-minute run does, so the database it opens at
    the end need not be the one it read config from at the start. Losing a whole
    scored run to `no such table` at the final step is the most expensive way to fail."""
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "gone.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))

    from sinks.sqlite import SqliteSink

    # No init_db() anywhere — the file does not exist at all.
    sink = SqliteSink(run_id="r1")
    assert sink.write_opportunities([_opp()]) == 1

    with session() as conn:
        assert len(repo.list_opportunities(conn, org_id=DEFAULT_ORG_ID)) == 1


# --- one exclusion mechanism, not two -----------------------------------------
#
# filters.py used to carry a hardcoded EXCLUDED_FUNDERS beside the remove list. Two
# problems: "excluded" meant two different things, only one of which the user could see —
# and the hardcoded one NEVER FIRED. It matched on funder name, and no source is called
# "County of San Diego Equity Impact Grant"; the registry has "County of San Diego".
# Zero occurrences across every recorded run, while presenting as a working §7 filter.

def test_the_hardcoded_exclusion_list_is_gone(db):
    import agent.filters as filters

    assert not hasattr(filters, "EXCLUDED_FUNDERS"), \
        "exclusion lives on the remove list, which the user controls — nowhere else"


def test_the_eight_former_partners_ship_on_the_remove_list(db):
    with session(db) as conn:
        removed = {f["name"] for f in repo.list_funders(conn, org_id=DEFAULT_ORG_ID) if not f["active"]}
    for name in ("San Diego Foundation", "Alliance Healthcare Foundation",
                 "Prebys Foundation", "City of San Diego Economic Development",
                 "City of San Diego Commission for Arts and Culture",
                 "California Arts Council", "The Morales Fund", "The Villegas Fund"):
        assert name in removed, f"{name} should be on the remove list"


def test_every_removal_records_why(db):
    with session(db) as conn:
        removed = [f for f in repo.list_funders(conn, org_id=DEFAULT_ORG_ID) if not f["active"]]
    assert removed
    for f in removed:
        assert f["exclude_reason"], f"{f['name']} was removed with no reason recorded"


def test_a_named_programme_can_be_removed_without_removing_its_funder(db):
    """§7 verbatim: "that is one program, not the whole County. Other County
    solicitations stay eligible." Said since day one, implemented only now."""
    from agent.run import _on_remove_list

    with session(db) as conn:
        excluded = repo.excluded_funder_names(conn, org_id=DEFAULT_ORG_ID)

    assert _on_remove_list("County of San Diego",
                           "Equity Impact Grant — County of San Diego", excluded)
    assert not _on_remove_list("County of San Diego",
                               "Community Enhancement Program", excluded)


def test_removing_a_funder_removes_all_of_its_pages(db):
    from agent.run import _on_remove_list

    with session(db) as conn:
        excluded = repo.excluded_funder_names(conn, org_id=DEFAULT_ORG_ID)
    assert _on_remove_list("California Arts Council", "Grants", excluded)
    assert _on_remove_list("California Arts Council", "Grant Programs", excluded)


def test_a_funder_not_on_the_list_is_untouched(db):
    from agent.run import _on_remove_list

    with session(db) as conn:
        excluded = repo.excluded_funder_names(conn, org_id=DEFAULT_ORG_ID)
    assert not _on_remove_list("The Parker Foundation", "Grant Making", excluded)
    assert not _on_remove_list("W.K. Kellogg Foundation", "Grantseekers", excluded)


def test_removed_funders_are_never_fetched(db):
    """The cheap half: they do not enter the source registry at all."""
    from agent.sources import Tier, sources_from_db

    fetchable, _ = sources_from_db(Tier.GOVERNMENT, [])
    names = {s.funder for s in fetchable}
    assert "San Diego Foundation" not in names
    assert "Prebys Foundation" not in names
    assert "The Parker Foundation" in names, "everyone else still searched"


def test_seeding_is_idempotent_and_does_not_duplicate_names(db):
    """The migration runs before seed_funders, so seeding remove-list rows there hit an
    empty table and duplicated every name once seed_funders added its url-keyed rows."""
    from collections import Counter

    init_db(db); init_db(db)
    with session(db) as conn:
        names = [f["name"] for f in repo.list_funders(conn, org_id=DEFAULT_ORG_ID)]
    dupes = [n for n, c in Counter(names).items() if c > 1]
    # Grants.gov and SAM.gov legitimately share a funder name; nothing else may.
    assert dupes == ["U.S. Federal Government"], f"unexpected duplicates: {dupes}"


# --- who counts as new ---------------------------------------------------------

def test_a_brand_new_install_has_not_been_onboarded(db):
    """The walkthrough has to happen at least once, and a fresh database is the one case
    where it definitely should.

    Nearly got this wrong: the v9 backfill first marked every row in `orgs`, and the v7
    migration creates `DEFAULT_ORG_ID` itself moments earlier — so a first-ever boot
    declared its own default org an experienced user and nobody ever saw onboarding.
    """
    with session(db) as conn:
        assert repo.get_settings(conn, org_id=DEFAULT_ORG_ID)["onboarding_done"] is False


def test_an_install_that_was_already_in_use_is_never_shown_onboarding(db):
    """The other direction, and the reported bug. Whether somebody is new is a stored
    fact; it used to be re-derived from "do you have a key, a program and a funder", so
    unticking the last programme threw an established account back to step one."""
    from app import secrets
    from app.db import init_db

    with session(db) as conn:
        # A database as it looked before this flag existed, with real use on it.
        secrets.store_api_key(conn, "sk-ant-months-of-use", org_id=DEFAULT_ORG_ID)
        conn.execute("DELETE FROM settings WHERE key='onboarding_done'")
        conn.execute("UPDATE meta SET value='8' WHERE key='schema_version'")

    init_db(db)          # the upgrade runs

    with session(db) as conn:
        assert repo.get_settings(conn, org_id=DEFAULT_ORG_ID)["onboarding_done"] is True


def test_unticking_every_program_does_not_make_an_account_new_again(db):
    """The exact sequence that was reported: untick everything, reload, and the app has
    apparently forgotten you."""
    from app.db import init_db

    with session(db) as conn:
        conn.execute("DELETE FROM settings WHERE key='onboarding_done'")
        conn.execute("UPDATE meta SET value='8' WHERE key='schema_version'")
        repo.create_run(conn, "r1", org_id=DEFAULT_ORG_ID)   # evidence of use

    init_db(db)

    with session(db) as conn:
        for p in repo.list_programs(conn, org_id=DEFAULT_ORG_ID):
            repo.update_program(conn, p["id"], {"active": False}, org_id=DEFAULT_ORG_ID)
        settings = repo.get_settings(conn, org_id=DEFAULT_ORG_ID)
        active = [p for p in repo.list_programs(conn, org_id=DEFAULT_ORG_ID) if p["active"]]

    assert active == [], "the precondition: nothing is ticked"
    assert settings["onboarding_done"] is True, \
        "a ticked checkbox is not what makes somebody a new user"


# --- v12: the IRS 990 cache is gone --------------------------------------------

_C990_FUNDERS = ("ein", "form_990_url", "form_990_year", "form_990_total_revenue",
                 "form_990_total_expenses", "form_990_checked_at")
_C990_OPPS = ("ein", "form_990_url", "form_990_year", "form_990_total_revenue",
              "form_990_total_expenses", "form_990_available")


def _readd_990_columns(conn) -> None:
    """Put a live database back into its v11 shape: the 990 columns, with data in them."""
    for table, cols in (("funders", _C990_FUNDERS), ("opportunities", _C990_OPPS)):
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in have:
                kind = "TEXT" if col in ("ein", "form_990_url", "form_990_checked_at") \
                    else "INTEGER"
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")


def test_the_990_columns_are_dropped_and_the_rows_survive(db):
    """The upgrade the live box runs. Losing the cache is the point; losing a nonprofit's
    funders or findings alongside it would not be."""
    from app.db import init_db

    with session(db) as conn:
        _readd_990_columns(conn)
        conn.execute(
            "INSERT INTO funders(org_id, id, name, url, added_by, created_at, updated_at,"
            " ein, form_990_year) VALUES(?,?,?,?,?,?,?,?,?)",
            (DEFAULT_ORG_ID, "f990", "MacArthur Foundation",
             "https://macfound.org/grants", "user", "2026-01-01", "2026-01-01",
             "36-2167817", 2024))
        conn.execute("UPDATE meta SET value='11' WHERE key='schema_version'")

    init_db(db)

    with session(db) as conn:
        for table in ("funders", "opportunities"):
            left = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
                    if "990" in r["name"] or r["name"] == "ein"]
            assert left == [], f"{table} still carries {left}"
        kept = repo.get_funder(conn, "f990", org_id=DEFAULT_ORG_ID)
        assert kept["name"] == "MacArthur Foundation"
        assert kept["url"] == "https://macfound.org/grants"


def test_the_990_drop_can_run_twice(db):
    """Migrations run on every boot. The second pass must be a no-op, not an error."""
    from app.db import init_db

    with session(db) as conn:
        _readd_990_columns(conn)
        conn.execute("UPDATE meta SET value='11' WHERE key='schema_version'")

    init_db(db)
    init_db(db)          # the reboot

    with session(db) as conn:
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
    assert int(version) >= 12


def test_a_pre_tenancy_database_still_upgrades_with_the_columns_gone(db):
    """The hazard the v7 intersect exists for.

    v7 rebuilds `funders` and `opportunities` by naming every column the old table had
    and selecting them into the new schema. A database that stopped at v5 or v6 still has
    the six 990 columns; the current schema does not. Without intersecting the two lists
    the INSERT fails with "table funders has no column named ein" — an upgrade that dies
    halfway, on somebody's only copy of their data.
    """
    from app.db import _migrate_to_org_scoped

    with session(db) as conn:
        # Strip the tenancy column back off one table and give it the old 990 columns,
        # which is what `_migrate_to_org_scoped` will find on a genuinely old database.
        conn.execute("DROP TABLE IF EXISTS funders")
        conn.execute("""CREATE TABLE funders(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT,
            sector TEXT NOT NULL DEFAULT 'other', active INTEGER NOT NULL DEFAULT 1,
            ein TEXT, form_990_url TEXT, form_990_year INTEGER,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute(
            "INSERT INTO funders(id, name, url, ein, created_at, updated_at) "
            "VALUES('old1','The Parker Foundation','https://theparkerfoundation.org',"
            "'95-1234567','2026-01-01','2026-01-01')")

        _migrate_to_org_scoped(conn)          # must not raise

        row = conn.execute("SELECT org_id, name, url FROM funders WHERE id='old1'").fetchone()

    assert row["org_id"] == DEFAULT_ORG_ID, "the row was adopted, not dropped"
    assert row["name"] == "The Parker Foundation"


def test_every_on_off_setting_is_declared_as_one(db):
    """A settings key whose default is "0" or "1" but which is missing from
    `_BOOL_SETTINGS` is a bug that looks like nothing until it ships.

    `share_funders` was added without it. `update_settings` therefore stored `str(True)`
    — the literal "True" — so the SQL that gates the shared pool on `value = '1'` never
    matched, and `get_settings` handed the browser the string "0", which is **truthy in
    JavaScript**: the opt-in checkbox rendered as ticked while sharing was off. Two
    contradictory bugs from one missing set entry.
    """
    from app.repo import _BOOL_SETTINGS

    looks_boolean = {k for k, v in DEFAULT_SETTINGS.items() if v in ("0", "1")}
    missing = sorted(looks_boolean - _BOOL_SETTINGS)
    assert not missing, (
        f"{', '.join(missing)} default to an on/off value but are not in _BOOL_SETTINGS, "
        "so they will be stored as 'True'/'False' and read back as a truthy string."
    )


def test_the_check_result_reaches_the_browser_as_a_tri_state(db):
    """NULL / true / false, and all three have to survive the trip.

    "Nobody has looked yet" is not "it failed", so this cannot collapse to a bool. And it
    cannot stay as SQLite's 1/0 either: those cross to JavaScript as integers, where
    `check_ok === true` is false for `1` — which is exactly how the Settings page came to
    report "0 of 2 shared" while the database held one pass and one failure.
    """
    with session(db) as conn:
        f = repo.create_funder(conn, {"name": "Checkable Trust",
                                      "url": "https://example.invalid/c"},
                               org_id=DEFAULT_ORG_ID)
        assert repo.get_funder(conn, f["id"], org_id=DEFAULT_ORG_ID)["check_ok"] is None

        for stored, expected in ((1, True), (0, False)):
            conn.execute("UPDATE funders SET check_ok=? WHERE id=? AND org_id=?",
                         (stored, f["id"], DEFAULT_ORG_ID))
            got = repo.get_funder(conn, f["id"], org_id=DEFAULT_ORG_ID)["check_ok"]
            assert got is expected, f"stored {stored!r} came back as {got!r}"


def test_changing_a_funders_address_makes_us_look_at_it_again(db):
    """Otherwise a shared funder whose link had a typo is marked unreachable for good:
    `recheck_shared` only picks up rows never checked, so there would be no way back."""
    with session(db) as conn:
        f = repo.create_funder(conn, {"name": "Moved Trust",
                                      "url": "https://example.invalid/old"},
                               org_id=DEFAULT_ORG_ID)
        conn.execute("UPDATE funders SET check_ok=0, check_note='did not load', "
                     "checked_at='2026-01-01' WHERE id=? AND org_id=?",
                     (f["id"], DEFAULT_ORG_ID))

        # Editing something else leaves the verdict alone — it is still about that page.
        repo.update_funder(conn, f["id"], {"notes": "rang them"}, org_id=DEFAULT_ORG_ID)
        assert repo.get_funder(conn, f["id"], org_id=DEFAULT_ORG_ID)["check_ok"] is False

        repo.update_funder(conn, f["id"], {"url": "https://example.invalid/new"},
                           org_id=DEFAULT_ORG_ID)
        after = repo.get_funder(conn, f["id"], org_id=DEFAULT_ORG_ID)
        assert after["check_ok"] is None and after["checked_at"] is None
