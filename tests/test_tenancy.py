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

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

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
    seed_starter_funders(path)
    seed_starter_programs(path)
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

def test_the_pre_tenancy_org_is_claimed_by_name_not_by_arriving_first(db, monkeypatch):
    """`DEFAULT_ORG_ID` holds the pilot's funders, findings and encrypted API key, so
    whoever lands in it can spend that key. Under open sign-up "whoever signs in first"
    would hand all of it to the first stranger who finds the URL."""
    monkeypatch.setenv("FUNDWORTHY_PILOT_EMAILS", "owner@example.org")
    with session(db) as conn:
        assert org_for_user(conn, "uid-owner", "Owner@Example.org") == DEFAULT_ORG_ID


def test_a_stranger_does_not_inherit_accumulated_findings(db, monkeypatch):
    """The security property, stated as a test: findings are the pilot's own work."""
    monkeypatch.delenv("FUNDWORTHY_PILOT_EMAILS", raising=False)
    with session(db) as conn:
        repo.save_opportunity(conn, _opp(), run_id="old", org_id=DEFAULT_ORG_ID)

        got = org_for_user(conn, "uid-stranger", "stranger@example.com")
        assert got != DEFAULT_ORG_ID
        # ...and the findings are still sitting there, waiting to be claimed.
        assert len(repo.list_opportunities(
            conn, org_id=DEFAULT_ORG_ID, month=month_key())) == 1


def test_a_stranger_does_not_inherit_a_saved_api_key(db, monkeypatch):
    monkeypatch.delenv("FUNDWORTHY_PILOT_EMAILS", raising=False)
    with session(db) as conn:
        secrets.store_api_key(conn, "sk-ant-THE-PILOTS-KEY", org_id=DEFAULT_ORG_ID)
        got = org_for_user(conn, "uid-stranger", "stranger@example.com")

        assert got != DEFAULT_ORG_ID
        assert secrets.read_api_key(conn, org_id=got) is None


def test_shipped_seed_content_does_not_count_as_somebody_elses_data(db, monkeypatch):
    """The 44 researched funders are a starting point every install gets, not the
    pilot's work. Counting them made a brand-new deployment look occupied — its first
    user got an empty org and the seeded funders sat orphaned beside it."""
    monkeypatch.delenv("FUNDWORTHY_PILOT_EMAILS", raising=False)
    with session(db) as conn:
        assert len(repo.list_funders(conn, org_id=DEFAULT_ORG_ID)) > 40   # seeded
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


# --- monthly spend cap --------------------------------------------------------

def test_spend_summary_counts_only_this_org(db):
    with session(db) as conn:
        repo.create_run(conn, "r_a", org_id=A)
        repo.update_run(conn, "r_a", usd_spent=3.50)
        repo.create_run(conn, "r_b", org_id=B)
        repo.update_run(conn, "r_b", usd_spent=1.25)

        assert repo.spend_summary(conn, org_id=A)["spent_usd"] == 3.50
        assert repo.spend_summary(conn, org_id=B)["spent_usd"] == 1.25


def test_the_monthly_cap_is_per_org_and_reports_headroom(db):
    with session(db) as conn:
        repo.update_settings(conn, {"monthly_budget_usd": 5.0}, org_id=B)
        repo.create_run(conn, "r_b", org_id=B)
        repo.update_run(conn, "r_b", usd_spent=4.0)

        summary = repo.spend_summary(conn, org_id=B)
        assert summary["cap_usd"] == 5.0
        assert summary["remaining_usd"] == 1.0
        assert summary["over_cap"] is False

        repo.update_run(conn, "r_b", usd_spent=5.5)
        assert repo.spend_summary(conn, org_id=B)["over_cap"] is True
        # ...and going over does not report negative headroom to the UI.
        assert repo.spend_summary(conn, org_id=B)["remaining_usd"] == 0.0

        # The other org is untouched by B blowing its budget.
        assert repo.spend_summary(conn, org_id=A)["over_cap"] is False


def test_a_run_is_refused_once_the_month_is_spent(db, monkeypatch):
    """The cap has to be checked before the run starts. `run_budget_usd` bounds one run,
    so without this an org could press Re-run all afternoon andevery run would pass."""
    from app.runner import RunManager

    with session(db) as conn:
        repo.update_settings(conn, {"monthly_budget_usd": 2.0}, org_id=A)
        repo.create_run(conn, "spent", org_id=A)
        repo.update_run(conn, "spent", usd_spent=2.5)

    with pytest.raises(RuntimeError, match="monthly limit"):
        RunManager().start(org_id=A)


# --- invitations --------------------------------------------------------------

def test_an_invite_moves_the_joiner_into_the_inviters_org(db):
    from app.db import create_invite, redeem_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        invite = create_invite(conn, owner, created_by="owner@example.org")

        joined = redeem_invite(conn, invite["code"], "uid-new", "colleague@example.org")

    assert joined == owner


def test_an_invite_is_single_use(db):
    from app.db import InviteError, create_invite, redeem_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        code = create_invite(conn, owner)["code"]
        redeem_invite(conn, code, "uid-1", "one@example.org")

        with pytest.raises(InviteError, match="already been used"):
            redeem_invite(conn, code, "uid-2", "two@example.org")


def test_a_bad_or_expired_invite_is_refused(db):
    from app.db import InviteError, create_invite, redeem_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        with pytest.raises(InviteError, match="not valid"):
            redeem_invite(conn, "ZZZZ-ZZZZ-ZZZZ", "uid-x", "x@example.org")

        code = create_invite(conn, owner)["code"]
        conn.execute("UPDATE invites SET expires_at='2020-01-01T00:00:00+00:00' "
                     "WHERE code=?", (code,))
        with pytest.raises(InviteError, match="expired"):
            redeem_invite(conn, code, "uid-y", "y@example.org")


def test_joining_by_invite_gives_access_to_that_orgs_data(db):
    """The point of the whole feature: two staff at one nonprofit see one dashboard."""
    from app.db import create_invite, redeem_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        repo.create_program(conn, {"name": "Shared Program"}, org_id=owner)
        code = create_invite(conn, owner)["code"]

        joined = redeem_invite(conn, code, "uid-new", "colleague@example.org")
        names = [p["name"] for p in repo.list_programs(conn, org_id=joined)]

    assert "Shared Program" in names


def test_a_revoked_invite_cannot_be_used(db):
    from app.db import InviteError, create_invite, redeem_invite, revoke_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        code = create_invite(conn, owner)["code"]
        assert revoke_invite(conn, code, owner) is True

        with pytest.raises(InviteError, match="not valid"):
            redeem_invite(conn, code, "uid-2", "two@example.org")


# --- a new org starts clean ---------------------------------------------------

def test_a_new_org_gets_the_starter_funders_but_none_of_the_pilots_own_data(db):
    """A newcomer gets the shipped funder lists — an empty list means Re-run does nothing
    — but nothing that belongs to the pilot: not their program cards, and not their
    remove-list decisions, which record relationships a stranger does not have."""
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")          # adopts the pilot org
        newcomer = org_for_user(conn, "uid-2", "second@example.org")

        funders = repo.list_funders(conn, org_id=newcomer)
        assert len(funders) > 40
        assert all(f["active"] for f in funders), (
            "the pilot's 'we already get money from them' is not a newcomer's")
        assert repo.list_programs(conn, org_id=newcomer) == []
        assert repo.get_settings(conn, org_id=newcomer)["min_award"] == 10_000


# --- deploy safety ------------------------------------------------------------

def test_a_deploy_pauses_new_searches_rather_than_killing_them(db, monkeypatch):
    """The drain gate. A run started thirty seconds before `systemctl restart` gets cut
    off at minute seven, and the org pays for a search it never sees."""
    from app.runner import RunManager, draining

    drain = db.parent / "draining"
    assert draining() is False

    drain.touch()
    try:
        assert draining() is True
        with pytest.raises(RuntimeError, match="being updated"):
            RunManager().start(org_id=A)
    finally:
        drain.unlink()

    assert draining() is False


def test_the_pipeline_salvages_what_it_scored_when_told_to_stop():
    """SIGTERM used to kill the process where it stood: the salvage block never ran and
    every scored result — plus the credit spent on it — was lost. It is now an ordinary
    exception, so the existing partial-results path catches it."""
    import signal

    from agent.run import RunInterrupted, _install_stop_handler

    _install_stop_handler()
    try:
        with pytest.raises(RunInterrupted):
            signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


def test_an_interrupted_run_is_catchable_as_an_ordinary_exception():
    """The salvage block catches `Exception`. If RunInterrupted ever became a
    BaseException subclass it would slip past it and the money would be lost again."""
    from agent.run import RunInterrupted

    assert issubclass(RunInterrupted, Exception)


def test_there_is_no_daily_run_limit_by_default(db, monkeypatch):
    """An org runs searches on its own Anthropic key. How many it wants is its own
    business and its own bill — rationing that would be us capping something we do not
    pay for. The ceiling exists only as a lever for a misbehaving account."""
    import app.runner as runner

    monkeypatch.setattr(runner, "MAX_RUNS_PER_DAY", 0)
    with session(db) as conn:
        for i in range(50):
            repo.create_run(conn, f"r{i}", org_id=A)

    # 50 runs today and the 51st is still allowed — it fails for want of a program to
    # search for, not because we said no.
    try:
        runner.RunManager().start(org_id=A)
    except RuntimeError as exc:
        assert "searches today" not in str(exc)


def test_a_daily_cap_can_still_be_imposed_on_a_misbehaving_account(db, monkeypatch):
    import app.runner as runner

    monkeypatch.setattr(runner, "MAX_RUNS_PER_DAY", 3)
    with session(db) as conn:
        for i in range(3):
            repo.create_run(conn, f"r{i}", org_id=A)
        assert repo.runs_today(conn, org_id=A) == 3
        assert repo.runs_today(conn, org_id=B) == 0      # counted per org, not globally

    with pytest.raises(RuntimeError, match="searches today"):
        runner.RunManager().start(org_id=A)


# --- the starter directory ----------------------------------------------------
#
# The reported bug: one account had 52 funders and the account created five minutes
# later had none. Nothing about that was a decision — it was an artefact of whoever
# signed in first claiming DEFAULT_ORG_ID and its seeded rows.

def test_two_new_accounts_get_the_same_thing(tmp_path, monkeypatch):
    """Whatever a new org starts with, it must not depend on who signed in first."""
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("FUNDWORTHY_PILOT_EMAILS", raising=False)
    init_db(path)

    with session(path) as conn:
        first = org_for_user(conn, "uid-1", "me@example.org")
        second = org_for_user(conn, "uid-2", "my.friend@example.org")

        assert first != second
        counts = {org: len(repo.list_funders(conn, org_id=org))
                  for org in (first, second)}
        assert len(set(counts.values())) == 1, counts
        assert all(n > 0 for n in counts.values()), "an empty list means Re-run does nothing"
        # Program cards are the exception: they describe one nonprofit's own work.
        for org in (first, second):
            assert repo.list_programs(conn, org_id=org) == []


def test_a_new_org_gets_no_program_cards(tmp_path, monkeypatch):
    """A funder list is shared knowledge — who gives money, in this city — so one org's
    research helps the next. A program card is the opposite: it describes what *this*
    nonprofit does, in their words, so another org's cards are not merely unhelpful but
    wrong. Seven cards about somebody else's arts programme made the app look configured
    when it was not, and the newcomer's first job was working out what to delete."""
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("FUNDWORTHY_PILOT_EMAILS", raising=False)
    init_db(path)

    with session(path) as conn:
        # Even the default org, which is what a first sign-in claims.
        assert repo.list_programs(conn, org_id=DEFAULT_ORG_ID) == []

        org = org_for_user(conn, "uid-1", "new@example.org")
        assert repo.list_programs(conn, org_id=org) == []
        # ...but they do get working settings, so the app is configured, just empty.
        assert repo.get_settings(conn, org_id=org)["min_award"] == 10_000


def test_a_run_with_no_program_cards_says_so_rather_than_searching_for_nothing(
        tmp_path, monkeypatch):
    """An empty dashboard is the intended first five minutes, so the pipeline has to
    handle it as a state rather than an error."""
    from agent.config import load_from_db

    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)

    cfg = load_from_db(path)
    assert cfg is not None
    assert cfg.programs == []
    assert cfg.programs_active == []


def test_a_starter_list_can_be_imported_and_is_idempotent(db):
    from app.db import import_starter_list

    with session(db) as conn:
        conn.execute("DELETE FROM funders WHERE org_id=?", (B,))

        added = import_starter_list(conn, "san-diego", B)
        assert added > 40
        assert len(repo.list_funders(conn, org_id=B)) == added

        # Importing twice adds nothing rather than duplicating.
        assert import_starter_list(conn, "san-diego", B) == 0


def test_importing_does_not_resurrect_a_funder_the_org_removed(db):
    """The remove list is the user's single exclusion lever. A re-import must not undo
    a decision they made — that was the seed-resurrection bug, in a new costume."""
    from app.db import import_starter_list

    with session(db) as conn:
        conn.execute("DELETE FROM funders WHERE org_id=?", (B,))
        import_starter_list(conn, "san-diego", B)

        victim = repo.list_funders(conn, org_id=B)[0]
        repo.update_funder(conn, victim["id"], {"active": False}, org_id=B)

        import_starter_list(conn, "san-diego", B)
        after = repo.get_funder(conn, victim["id"], org_id=B)
        assert after["active"] is False


def test_the_federal_database_is_its_own_list(db):
    """A Chicago nonprofit wants Grants.gov and does not want 58 San Diego foundations,
    so those cannot be one indivisible blob."""
    from agent.directory import get

    national = get("national")
    assert [s.adapter for s in national.sources] == ["grants_gov"]
    assert all(s.adapter is None for s in get("san-diego").sources)


def test_importing_is_scoped_to_your_own_org(db):
    from app.db import import_starter_list

    with session(db) as conn:
        conn.execute("DELETE FROM funders WHERE org_id=?", (B,))
        before_a = len(repo.list_funders(conn, org_id=A))

        import_starter_list(conn, "national", B)

        assert len(repo.list_funders(conn, org_id=B)) == 1
        assert len(repo.list_funders(conn, org_id=A)) == before_a


def test_a_new_account_can_actually_run_a_search(db):
    """The production bug this fixes: a new account opened onto an empty funder list, so
    Re-run had nothing to search and did nothing. Whatever else is true of a new org, the
    pipeline must have sources to work with."""
    from agent.sources import Tier, sources_from_db

    with session(db) as conn:
        newcomer = org_for_user(conn, "uid-new", "newcomer@example.org")
        assert len(repo.list_funders(conn, org_id=newcomer)) > 40

    fetchable, _ = sources_from_db(Tier.GOVERNMENT, [], db_path=db, org_id=newcomer)
    assert len(fetchable) > 0, "a new org's funders never reach the crawler"


def test_the_starter_lists_include_the_grant_databases(db):
    """Grants.gov and the CA portal are searched as databases rather than crawled, and
    they are the two sources that are useful to an org anywhere. A new account that got
    only hand-researched San Diego pages would be missing the half that generalises."""
    with session(db) as conn:
        newcomer = org_for_user(conn, "uid-new", "newcomer@example.org")
        adapters = {f["adapter"] for f in repo.list_funders(conn, org_id=newcomer)}

    assert {"grants_gov", "ca_grants_portal"} <= adapters
