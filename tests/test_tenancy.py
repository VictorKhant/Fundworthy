"""Tenant isolation. Two orgs on one install must not be able to see, spend, or
destroy each other's anything.

These tests exist because the app was built single-tenant on purpose and then put on the
internet behind a sign-in. Everything here was, at the commit before these tests landed, a
real observable defect on the live deployment rather than a hypothetical: one shared
database with no `org_id` column anywhere, and one shared Anthropic key.

The shape of every test is the same, deliberately: set something up as org A, act as
org B, and assert that org A is untouched. A test that only checks org B "gets its own"
would pass against an implementation that simply overwrites A.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import archive, repo, secrets           # noqa: E402
from app.db import (DEFAULT_ORG_ID, ensure_org, init_db, month_key,  # noqa: E402
                    org_for_user, session)
from agent.models import Opportunity, stable_id  # noqa: E402

A = DEFAULT_ORG_ID
B = "org_second"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh install with two orgs: the default one, and a second that has signed in."""
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)
    with session(path) as conn:
        ensure_org(conn, B, "Second Nonprofit")
    return path


def _opp(**over):
    """A minimal Opportunity. The default url/title pair is the same for both orgs on
    purpose — that collision is the thing being tested."""
    fields = dict(
        title="Community Arts Grant",
        funder="Example Foundation",
        source_url="https://example.invalid/grant",
        award_min=25_000, award_max=50_000,
        deadline=date.today() + timedelta(days=60),
        estimated_effort_hours=10,
        program_match=[], score=70, score_rationale="fits",
        verified=True, needs_human_check=False,
        fetched_at=datetime.now(timezone.utc),
    )
    fields.update(over)
    fields.setdefault("id", stable_id(fields["source_url"], fields["title"]))
    return Opportunity(**fields)


# --- the API key --------------------------------------------------------------

def test_a_second_org_saving_a_key_does_not_replace_the_first(db):
    """The reported bug, directly. One `settings` row keyed only on 'anthropic_api_key'
    meant the second org to paste a key silently destroyed the first org's."""
    with session(db) as conn:
        secrets.store_api_key(conn, "sk-ant-AAA-first", org_id=A)
        secrets.store_api_key(conn, "sk-ant-BBB-second", org_id=B)

        assert secrets.read_api_key(conn, org_id=A) == "sk-ant-AAA-first"
        assert secrets.read_api_key(conn, org_id=B) == "sk-ant-BBB-second"


def test_clearing_one_orgs_key_leaves_the_other_alone(db):
    with session(db) as conn:
        secrets.store_api_key(conn, "sk-ant-AAA-first", org_id=A)
        secrets.store_api_key(conn, "sk-ant-BBB-second", org_id=B)
        secrets.clear_api_key(conn, org_id=B)

        assert secrets.read_api_key(conn, org_id=A) == "sk-ant-AAA-first"
        assert secrets.read_api_key(conn, org_id=B) is None


def test_a_new_org_does_not_inherit_the_servers_environment_key(db, monkeypatch):
    """The other half of the reported bug, and the more expensive half.

    `ANTHROPIC_API_KEY` in the VM's .env is the deployer's own key. Before this, an org
    that had never pasted anything fell through to it — so a brand-new account ran, looked
    like it worked, and billed somebody else. A new org gets its own key or none.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SERVER-env")
    with session(db) as conn:
        key_b, source_b = secrets.resolve_api_key(conn, org_id=B)
        assert key_b is None
        assert source_b is None

        # The default org keeps the fallback: that is the single-tenant install, and it
        # is the only org the .env key can honestly be said to belong to.
        key_a, source_a = secrets.resolve_api_key(conn, org_id=A)
        assert key_a == "sk-ant-SERVER-env"
        assert source_a == secrets.SOURCE_ENVIRONMENT


def test_an_orgs_own_key_still_wins_over_the_environment(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SERVER-env")
    with session(db) as conn:
        secrets.store_api_key(conn, "sk-ant-OWN", org_id=B)
        assert secrets.resolve_api_key(conn, org_id=B) == (
            "sk-ant-OWN", secrets.SOURCE_SETTINGS)


# --- findings -----------------------------------------------------------------

def test_the_same_grant_page_is_a_separate_row_for_each_org(db):
    """`opportunities.id` is stable_id(source_url, title) — derived, not random — so two
    orgs looking at the same grant compute the same id. With a bare `id PRIMARY KEY` the
    second write overwrote the first org's row, taking its score and rationale with it."""
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(score=70), run_id="runA", org_id=A)
        repo.save_opportunity(conn, _opp(score=12), run_id="runB", org_id=B)

        rows_a = repo.list_opportunities(conn, org_id=A, month=month_key())
        rows_b = repo.list_opportunities(conn, org_id=B, month=month_key())

    assert [r["score"] for r in rows_a] == [70]
    assert [r["score"] for r in rows_b] == [12]


def test_one_org_cannot_see_anothers_findings(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="runA", org_id=A)
        assert repo.list_opportunities(conn, org_id=B, month=month_key()) == []


def test_the_start_of_run_purge_only_touches_its_own_org(db):
    """`purge_old_months` runs before anything else in every run. Unscoped, any org
    pressing Re-run on the 1st of a month wiped every other org's archive first."""
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="runA", org_id=A)
        repo.save_opportunity(
            conn, _opp(source_url="https://example.invalid/b", title="Other"),
            run_id="runB", org_id=B)
        conn.execute("UPDATE opportunities SET month_key='2020-01'")

        removed = archive.purge_old_months(conn, org_id=B)

        assert removed == 1
        assert len(repo.list_opportunities(conn, org_id=A, month="2020-01")) == 1
        assert repo.list_opportunities(conn, org_id=B, month="2020-01") == []


def test_dedup_does_not_hide_a_grant_the_other_org_already_found(db):
    """The quiet one. Unscoped dedup meant the second org to run in a month inherited the
    first org's 'already seen' set, so grants were dropped in the free tier — never
    fetched, never scored, never shown, and nothing in the log to say why."""
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="runA", org_id=A)

        assert archive.seen_this_month(conn, _opp().id, org_id=A) is True
        assert archive.seen_this_month(conn, _opp().id, org_id=B) is False
        assert archive.seen_ids_this_month(conn, org_id=B) == set()


def test_month_summary_counts_only_your_own_months(db):
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="runA", org_id=A)
        assert archive.month_summary(conn, org_id=B)["months"] == []
        assert archive.month_summary(conn, org_id=A)["months"][0]["total"] == 1


# --- funders, programs, settings ----------------------------------------------

def test_one_orgs_remove_list_does_not_filter_anothers_search(db):
    """CLAUDE.md calls the remove list "the single exclusion lever, and it is the user's".
    Shared, it was everybody's: unticking a funder you already have a relationship with
    deleted that funder from every other nonprofit's search too."""
    with session(db) as conn:
        # `create_funder` keys the id on the name alone, so both orgs get the same id —
        # which is exactly the collision the composite primary key has to survive.
        a_row = repo.create_funder(conn, {"name": "Shared Foundation"}, org_id=A)
        b_row = repo.create_funder(conn, {"name": "Shared Foundation"}, org_id=B)
        assert a_row["id"] == b_row["id"]

        repo.update_funder(conn, b_row["id"], {"active": False}, org_id=B)

        assert "shared foundation" in repo.excluded_funder_names(conn, org_id=B)
        assert "shared foundation" not in repo.excluded_funder_names(conn, org_id=A)


def test_deleting_a_funder_only_deletes_your_copy(db):
    with session(db) as conn:
        repo.create_funder(conn, {"name": "Shared Foundation"}, org_id=A)
        shared_id = repo.create_funder(
            conn, {"name": "Shared Foundation"}, org_id=B)["id"]

        assert repo.delete_funder(conn, shared_id, org_id=B) is True
        assert "Shared Foundation" in [f["name"] for f in
                                       repo.list_funders(conn, org_id=A)]
        # ...and B cannot delete it a second time by reaching into A's rows.
        assert repo.delete_funder(conn, shared_id, org_id=B) is False


def test_program_cards_are_not_shared(db):
    """A program card is the closest thing a small nonprofit has to written strategy, and
    an unscoped `list_programs(active_only=True)` sent every org's into one system
    prompt — on whichever key happened to be stored."""
    with session(db) as conn:
        repo.create_program(conn, {"name": "Arts Education", "active": True}, org_id=B)
        b_cards = repo.list_programs(conn, org_id=B, active_only=True)
        a_cards = repo.list_programs(conn, org_id=A, active_only=True)

    assert [c["name"] for c in b_cards] == ["Arts Education"]
    assert "Arts Education" not in [c["name"] for c in a_cards]


def test_two_orgs_may_use_the_same_program_slug(db):
    """Slugs are unique per org, not globally — otherwise the second nonprofit to create
    an "Arts Education" card silently gets ARTS_EDUCATION_2 and no explanation."""
    with session(db) as conn:
        a = repo.create_program(conn, {"name": "Arts Education"}, org_id=A)
        b = repo.create_program(conn, {"name": "Arts Education"}, org_id=B)
    assert a["slug"] == b["slug"] == "ARTS_EDUCATION"


def test_settings_are_per_org(db):
    with session(db) as conn:
        repo.update_settings(conn, {"min_award": 50_000}, org_id=B)
        assert repo.get_settings(conn, org_id=B)["min_award"] == 50_000
        assert repo.get_settings(conn, org_id=A)["min_award"] == 10_000


def test_runs_are_listed_per_org(db):
    with session(db) as conn:
        repo.create_run(conn, "run_a", org_id=A, started_by="a@example.org")
        repo.create_run(conn, "run_b", org_id=B, started_by="b@example.org")

        assert [r["id"] for r in repo.list_runs(conn, org_id=B)] == ["run_b"]
        assert repo.latest_run(conn, org_id=A)["id"] == "run_a"
        # A run id from another org is not readable even knowing the id.
        assert repo.get_run(conn, "run_a", org_id=B) is None


# --- users and org assignment -------------------------------------------------

def test_the_first_person_to_sign_in_adopts_the_existing_data(db):
    """The pilot org's funders and findings predate tenancy. Stranding them behind a new
    empty org would read as data loss to the person who has been using them."""
    with session(db) as conn:
        assert org_for_user(conn, "uid-1", "first@example.org") == DEFAULT_ORG_ID


def test_the_second_person_to_sign_in_gets_their_own_org(db):
    """The reported symptom: a teammate creating an account landed in the first user's
    data, with the first user's key."""
    with session(db) as conn:
        first = org_for_user(conn, "uid-1", "first@example.org")
        second = org_for_user(conn, "uid-2", "second@example.org")

    assert second != first
    assert second != DEFAULT_ORG_ID


def test_signing_in_again_returns_the_same_org(db):
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        second = org_for_user(conn, "uid-2", "second@example.org")
        assert org_for_user(conn, "uid-2", "second@example.org") == second


def test_a_rebuilt_firebase_account_keeps_its_org(db):
    """Same person, new `sub` claim — a deleted-and-remade Google account, or a rebuilt
    Firebase project. Matching on the address keeps their dashboard rather than handing
    them an empty one."""
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        original = org_for_user(conn, "uid-2", "second@example.org")
        assert org_for_user(conn, "uid-2-NEW", "second@example.org") == original


# --- seeding ------------------------------------------------------------------

def test_a_deleted_seed_funder_stays_deleted_across_restarts(db):
    """`init_db(seed=True)` runs on every process start and every pipeline run. It used to
    re-run the seeders each time, so deleting a funder that means nothing to you lasted
    until the next restart — and then all 44 came back, re-activated."""
    with session(db) as conn:
        victim = repo.list_funders(conn, org_id=A)[0]
        before = len(repo.list_funders(conn, org_id=A))
        repo.delete_funder(conn, victim["id"], org_id=A)

    init_db(db)          # a restart

    with session(db) as conn:
        names = [f["name"] for f in repo.list_funders(conn, org_id=A)]
    assert victim["name"] not in names
    assert len(names) == before - 1


# --- run lifecycle ------------------------------------------------------------

def test_a_run_interrupted_by_a_restart_is_not_left_running_for_ever(db):
    """`RunManager` is per-process memory, so a `systemctl restart` — the last step of
    every deploy — leaves the row at 'running' with nothing alive to finish it. The
    dashboard then shows a spinner for a search that died days ago."""
    with session(db) as conn:
        repo.create_run(conn, "run_x", org_id=A)
        assert repo.get_run(conn, "run_x")["status"] == "running"

        assert repo.reconcile_interrupted_runs(conn) == 1

        row = repo.get_run(conn, "run_x")
        assert row["status"] == "failed"
        assert row["stop_reason"] == "interrupted_by_restart"
        assert row["finished_at"]

        # Idempotent: a second boot has nothing left to reconcile.
        assert repo.reconcile_interrupted_runs(conn) == 0
