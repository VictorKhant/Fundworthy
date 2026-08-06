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

        # The default org keeps the fallback *on a local install*: one org, one machine,
        # and the person who wrote the file is the person paying for the key.
        key_a, source_a = secrets.resolve_api_key(conn, org_id=A)
        assert key_a == "sk-ant-SERVER-env"
        assert source_a == secrets.SOURCE_ENVIRONMENT


def test_the_environment_key_stops_applying_once_sign_in_is_configured(db, monkeypatch):
    """The hole the per-org rule left open, and the only one left where somebody else
    pays.

    "Default org only" sounds like it bounds the damage, and on a laptop it does. On a
    deployed box the default org is not a hypothetical: it is the pilot named in
    `FUNDWORTHY_PILOT_EMAILS`, or the first person to sign in to an empty install. That
    one account searched on the deployer's `ANTHROPIC_API_KEY` — set once, in a systemd
    EnvironmentFile, by whoever provisioned the VM — indefinitely, while its Settings page
    correctly reported that no key was saved.

    So the variable is scoped to the shape it was written for: a single-tenant install
    with no sign-in. A key left in a deployed box's environment is inert, which is the
    property worth having — "remember to delete this line" is not a safeguard.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SERVER-env")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "fundworthy-live")

    with session(db) as conn:
        assert secrets.resolve_api_key(conn, org_id=A) == (None, None), (
            "not even the default org, once there are accounts")
        assert secrets.resolve_api_key(conn, org_id=B) == (None, None)

        # And the org's own key is unaffected — this narrows the fallback, nothing else.
        secrets.store_api_key(conn, "sk-ant-THEIR-OWN", org_id=A)
        assert secrets.resolve_api_key(conn, org_id=A) == (
            "sk-ant-THEIR-OWN", secrets.SOURCE_SETTINGS)


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

    assert joined["org_id"] == owner
    assert joined["left_org"] is None, "a brand-new person left nothing behind"
    assert joined["stranded"] is False


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
        names = [p["name"] for p in repo.list_programs(conn, org_id=joined["org_id"])]

    assert "Shared Program" in names


def test_a_revoked_invite_cannot_be_used(db):
    from app.db import InviteError, create_invite, redeem_invite, revoke_invite

    with session(db) as conn:
        owner = org_for_user(conn, "uid-owner", "owner@example.org")
        code = create_invite(conn, owner)["code"]
        assert revoke_invite(conn, code, owner) is True

        with pytest.raises(InviteError, match="not valid"):
            redeem_invite(conn, code, "uid-2", "two@example.org")


# --- joining is also leaving ---------------------------------------------------
#
# `redeem_invite` MOVES somebody, so it has to answer the same two questions closing an
# account does. It used to be a bare `UPDATE users SET org_id`, which answered neither:
# an admin could walk out of an org with colleagues still in it and freeze it, and a
# sole member could leave their org behind with a live encrypted API key in it.

def test_the_last_person_out_strands_the_org_they_left(db):
    """Same rule as closing an account: findings and the key go, hand-added funders stay.

    A key left behind is the part that actually matters — it is a live credential in an
    org that now has nobody who can sign in to remove it.
    """
    from app import secrets
    from app.db import create_invite, redeem_invite

    with session(db) as conn:
        # The first signer-in adopts the pre-tenancy org and its 60-odd seeded funders,
        # so the person under test has to be the second. Otherwise "the funders they
        # added by hand" is the whole starter list and the test passes for the wrong
        # reason — or fails for one.
        org_for_user(conn, "uid-pilot", "pilot@example.org")
        old = org_for_user(conn, "uid-mover", "mover@example.org")
        secrets.store_api_key(conn, "sk-ant-leftbehind", org_id=old)
        repo.create_funder(conn, {"name": "Their Own Find",
                                  "url": "https://own.example/grants"}, org_id=old)
        repo.create_run(conn, "r-old", org_id=old)

        other = org_for_user(conn, "uid-host", "host@example.org")
        code = create_invite(conn, other)["code"]

        result = redeem_invite(conn, code, "uid-mover", "mover@example.org")

        assert result["org_id"] == other
        assert result["left_org"] == old
        assert result["stranded"] is True

        key, _source = secrets.resolve_api_key(conn, org_id=old)
        assert not key, "a live credential outlived the account it belonged to"
        assert repo.list_runs(conn, org_id=old) == []
        kept = [f["name"] for f in repo.list_funders(conn, org_id=old)]
        assert kept == ["Their Own Find"], "hand-added funders are the part worth keeping"


def test_an_admin_with_colleagues_cannot_join_their_way_out(db):
    """Otherwise the only person who can invite or remove anybody leaves, and the org is
    frozen with no way to unfreeze it. Closing an account already refuses this."""
    from app.db import InviteError, create_invite, redeem_invite

    with session(db) as conn:
        home = org_for_user(conn, "uid-boss", "boss@example.org")
        colleague_code = create_invite(conn, home)["code"]
        redeem_invite(conn, colleague_code, "uid-staff", "staff@example.org")

        elsewhere = org_for_user(conn, "uid-other", "other@example.org")
        code = create_invite(conn, elsewhere)["code"]

        with pytest.raises(InviteError, match="[Hh]and it over"):
            redeem_invite(conn, code, "uid-boss", "boss@example.org")

        # And nothing happened: not the move, and not the invitation either.
        assert org_for_user(conn, "uid-boss", "boss@example.org") == home
        row = conn.execute("SELECT redeemed_at FROM invites WHERE code=?",
                           (code,)).fetchone()
        assert row["redeemed_at"] is None, \
            "a refused attempt burned a single-use code"


def test_a_colleague_who_is_not_the_admin_may_leave_freely(db):
    """The other side of the rule. Somebody who is not holding the keys is not trapped,
    and the org they leave keeps everything because it still has members."""
    from app.db import create_invite, redeem_invite

    with session(db) as conn:
        org_for_user(conn, "uid-pilot", "pilot@example.org")   # adopts the seeded org
        home = org_for_user(conn, "uid-boss", "boss@example.org")
        repo.create_funder(conn, {"name": "Stays Put",
                                  "url": "https://stays.example/grants"}, org_id=home)
        redeem_invite(conn, create_invite(conn, home)["code"],
                      "uid-staff", "staff@example.org")

        elsewhere = org_for_user(conn, "uid-other", "other@example.org")
        result = redeem_invite(conn, create_invite(conn, elsewhere)["code"],
                               "uid-staff", "staff@example.org")

        assert result["stranded"] is False
        assert [f["name"] for f in repo.list_funders(conn, org_id=home)] == ["Stays Put"]


def test_redeeming_a_code_for_the_org_you_are_already_in_is_a_no_op(db):
    """Re-pasting a code you have used should say "you are in", not throw — and must not
    take you out through `remove_member` and straight back in, which on a one-person org
    would strand it and delete the findings you are looking at."""
    from app.db import create_invite, redeem_invite

    with session(db) as conn:
        home = org_for_user(conn, "uid-boss", "boss@example.org")
        repo.create_run(conn, "r-keep", org_id=home)
        code = create_invite(conn, home)["code"]

        result = redeem_invite(conn, code, "uid-boss", "boss@example.org")

        assert result == {"org_id": home, "left_org": None, "stranded": False}
        assert len(repo.list_runs(conn, org_id=home)) == 1, "it deleted its own org"


# --- a new org starts clean ---------------------------------------------------

def test_a_new_org_starts_empty_and_inherits_nothing_of_the_pilots(db):
    """A newcomer gets working settings and nothing else — no funders, no program cards,
    and none of the pilot's remove-list decisions, which record relationships a stranger
    does not have.

    Funders have been decided three times (see `seed_org`). They are seeded into nobody
    again, and the thing that made that broken before is gone: onboarding step 3 is the
    researched lists as one-click imports, and `runner.preflight` refuses a search with
    no funders instead of running one that silently does nothing.
    """
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")          # adopts the pilot org
        newcomer = org_for_user(conn, "uid-2", "second@example.org")

        assert repo.list_funders(conn, org_id=newcomer) == [], "they choose their own"
        assert repo.list_programs(conn, org_id=newcomer) == []
        assert repo.get_settings(conn, org_id=newcomer)["min_award"] == 10_000
        # And the pilot keeps everything it had.
        assert len(repo.list_funders(conn, org_id=A)) > 40


def test_an_empty_funder_list_is_a_question_rather_than_a_dead_end(db):
    """The reason seeding-into-nobody is safe now. It was tried before and reverted,
    because a new account pressed Search and nothing happened with no explanation."""
    from app.runner import preflight

    with session(db) as conn:
        # The first signer-in adopts the pre-tenancy org, so a genuine newcomer is the
        # second. Without this the "newcomer" *is* the pilot org, with its 40 funders,
        # and the test passes for the wrong reason.
        org_for_user(conn, "uid-1", "first@example.org")
        newcomer = org_for_user(conn, "uid-2", "second@example.org")
        codes = [b["code"] for b in preflight(conn, org_id=newcomer, no_llm=True)]

    assert "no_funders" in codes, "the search is refused, and it says which page fixes it"


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
        # Which is now zero, for both. The fairness property is the one under test — that
        # what you start with does not depend on who arrived first — and it holds whether
        # the answer is "everything" or "nothing". It is nothing: a Chicago nonprofit
        # should not be handed 58 San Diego foundations, and onboarding asks instead.
        assert all(n == 0 for n in counts.values()), counts
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


# --- leaving an organization --------------------------------------------------
#
# Two ways a person stops belonging to an org — the admin removes them, or they close
# their own account — and both have to end in the same place: no route can resolve them
# to that org again, so its findings, its funders and its encrypted API key are all
# equally out of reach. The `users` row is the whole mechanism, which is why these tests
# check the consequence rather than the row.

def _member(conn, uid, email, org_id):
    from app.db import now_iso
    conn.execute(
        "INSERT INTO users(uid, email, org_id, created_at, last_seen_at) "
        "VALUES(?,?,?,?,?)", (uid, email, org_id, now_iso(), now_iso()))


def test_the_first_person_in_an_org_administers_it(db):
    from app.db import org_members, org_owner

    with session(db) as conn:
        _member(conn, "u1", "founder@a.org", B)
        _member(conn, "u2", "colleague@a.org", B)
        conn.execute("UPDATE orgs SET owner_uid='u1' WHERE id=?", (B,))

        assert org_owner(conn, B) == "u1"
        badges = {m["email"]: m["is_admin"] for m in org_members(conn, B)}
        assert badges == {"founder@a.org": True, "colleague@a.org": False}


def test_an_org_whose_owner_vanished_promotes_somebody_rather_than_locking_up(db):
    """An org with members and no valid owner can never remove anyone or hand itself on
    again. Pre-ownership orgs and a deleted owner both produce exactly that, so a
    dangling `owner_uid` falls through to the earliest remaining member."""
    from app.db import org_owner

    with session(db) as conn:
        _member(conn, "u1", "first@a.org", B)
        _member(conn, "u2", "second@a.org", B)
        conn.execute("UPDATE orgs SET owner_uid='ghost' WHERE id=?", (B,))

        assert org_owner(conn, B) == "u1"
        # And it healed the row rather than recomputing it every time.
        assert conn.execute("SELECT owner_uid FROM orgs WHERE id=?",
                            (B,)).fetchone()["owner_uid"] == "u1"


def test_a_removed_member_can_no_longer_resolve_to_that_org(db):
    """The removal *is* the revocation. Every /api route resolves the caller's org from
    this row, so with it gone there is no path back to the funders, the findings or the
    key — and the next sign-in provisions a fresh empty org, which is the "they see
    onboarding like a new user" the removal is supposed to produce."""
    from app.db import remove_member

    with session(db) as conn:
        _member(conn, "u1", "boss@a.org", B)
        _member(conn, "u2", "leaver@a.org", B)
        secrets.store_api_key(conn, "sk-ant-ORG-B-KEY", org_id=B)

        assert remove_member(conn, "u2", B) is True

    with session(db) as conn:
        landed = org_for_user(conn, "u2", "leaver@a.org")
        assert landed != B, "signing in again must not put them back where they were"
        assert secrets.read_api_key(conn, org_id=landed) is None, "no key comes with them"
        assert repo.get_settings(conn, org_id=landed)["onboarding_done"] is False, \
            "a fresh org means the walkthrough, like any new account"
        # And the org they left is untouched.
        assert secrets.read_api_key(conn, org_id=B) == "sk-ant-ORG-B-KEY"


def test_the_last_one_out_loses_the_findings_and_the_key_but_not_the_funders(db):
    """The asymmetry is the point, not an oversight.

    Findings are one nonprofit's private research and nobody can ever ask for them again.
    A funder is a name, a grants page and a sector — somebody's hand-added research that
    is useful to the next nonprofit in that city, and the reason for keeping it.
    """
    from app.db import remove_member

    with session(db) as conn:
        _member(conn, "solo", "only@b.org", B)
        secrets.store_api_key(conn, "sk-ant-DOOMED", org_id=B)
        repo.create_funder(conn, {"name": "Hand Added Trust",
                                  "url": "https://example.invalid/g"}, org_id=B)
        repo.create_run(conn, "run_b", org_id=B)
        repo.save_opportunity(conn, _opp(), run_id="run_b", org_id=B)
        before = len(repo.list_funders(conn, org_id=B))
        assert before and repo.list_opportunities(conn, org_id=B, month=month_key())

        remove_member(conn, "solo", B)

    with session(db) as conn:
        assert repo.list_opportunities(conn, org_id=B, month=month_key()) == []
        assert repo.list_runs(conn, org_id=B) == []
        assert secrets.read_api_key(conn, org_id=B) is None, \
            "a live credential must not outlive the account it belonged to"
        assert len(repo.list_funders(conn, org_id=B)) == before, \
            "the funder list is the one thing worth keeping"
        assert conn.execute("SELECT 1 FROM orgs WHERE id=?", (B,)).fetchone(), \
            "the org row stays — the kept funders point at it"


def test_one_member_leaving_takes_nothing_from_the_ones_who_stay(db):
    from app.db import remove_member

    with session(db) as conn:
        _member(conn, "u1", "stays@b.org", B)
        _member(conn, "u2", "goes@b.org", B)
        secrets.store_api_key(conn, "sk-ant-SHARED", org_id=B)
        repo.create_run(conn, "run_b", org_id=B)
        repo.save_opportunity(conn, _opp(), run_id="run_b", org_id=B)

        remove_member(conn, "u2", B)

        assert repo.list_opportunities(conn, org_id=B, month=month_key())
        assert secrets.read_api_key(conn, org_id=B) == "sk-ant-SHARED"


def test_removing_somebody_never_touches_another_org(db):
    """The shape every test in this file uses: act on B, assert A is untouched."""
    from app.db import remove_member

    with session(db) as conn:
        _member(conn, "u_b", "solo@b.org", B)
        secrets.store_api_key(conn, "sk-ant-A-KEY", org_id=A)
        repo.create_run(conn, "run_a", org_id=A)
        repo.save_opportunity(conn, _opp(), run_id="run_a", org_id=A)

        remove_member(conn, "u_b", B)          # strands B entirely

        assert secrets.read_api_key(conn, org_id=A) == "sk-ant-A-KEY"
        assert repo.list_opportunities(conn, org_id=A, month=month_key())
        assert repo.list_runs(conn, org_id=A)


# --- funders one nonprofit offers to another ------------------------------------
#
# The only feature here that deliberately crosses the tenant boundary, so it gets the
# same treatment as everything else in this file: set it up as one org, look as another,
# and assert that nothing which was not offered came with it.

def _shared_funder(conn, org_id, name, url, *, check_ok=1):
    f = repo.create_funder(conn, {"name": name, "url": url, "sector": "foundation"},
                           org_id=org_id)
    conn.execute("UPDATE funders SET check_ok=?, check_note=?, checked_at=? "
                 "WHERE org_id=? AND id=?",
                 (check_ok, "The page opened and names an award amount.",
                  "2026-08-05T00:00:00+00:00", org_id, f["id"]))
    repo.update_settings(conn, {"share_funders": True}, org_id=org_id)
    return f


def test_nothing_is_shared_until_an_org_ticks_the_box(db):
    """Opt in, and the default is off. A funder list is not private, but "not private" is
    not "ours to publish on their behalf"."""
    with session(db) as conn:
        f = repo.create_funder(conn, {"name": "Quiet Trust",
                                      "url": "https://example.invalid/q"}, org_id=B)
        conn.execute("UPDATE funders SET check_ok=1 WHERE org_id=? AND id=?",
                     (B, f["id"]))
        assert repo.get_settings(conn, org_id=B)["share_funders"] is False
        assert repo.shared_funders(conn, org_id=A) == []

        repo.update_settings(conn, {"share_funders": True}, org_id=B)
        assert [x["name"] for x in repo.shared_funders(conn, org_id=A)] == ["Quiet Trust"]


def test_only_hand_added_funders_are_ever_offered(db):
    """Re-sharing the San Diego list back to people who can already import it contributes
    nothing, and would bury the handful of real contributions in 58 duplicates."""
    with session(db) as conn:
        repo.update_settings(conn, {"share_funders": True}, org_id=A)   # pilot shares
        conn.execute("UPDATE funders SET check_ok=1 WHERE org_id=?", (A,))

        names = {x["name"] for x in repo.shared_funders(conn, org_id=B)}
        assert names == set(), "the starter lists are already on offer to everybody"


def test_a_page_that_did_not_load_is_never_offered(db):
    """Failing the check is disqualifying; passing it is only permission to be offered.
    A dead link wastes the next person's time for certain."""
    with session(db) as conn:
        _shared_funder(conn, B, "Gone Away Fund", "https://example.invalid/404",
                       check_ok=0)
        assert repo.shared_funders(conn, org_id=A) == []


def test_an_unchecked_funder_waits_rather_than_being_offered(db):
    with session(db) as conn:
        repo.create_funder(conn, {"name": "Not Looked At Yet",
                                  "url": "https://example.invalid/n"}, org_id=B)
        repo.update_settings(conn, {"share_funders": True}, org_id=B)
        assert repo.shared_funders(conn, org_id=A) == []


def test_sharing_carries_the_funder_and_nothing_else_about_the_org(db):
    """The thing that would make this feature unshippable is leaking who is looking for
    what. Findings, spending, program cards and the org's name must not travel."""
    with session(db) as conn:
        _shared_funder(conn, B, "Open Trust", "https://example.invalid/open")
        repo.update_settings(conn, {"org_name": "Second Nonprofit"}, org_id=B)
        repo.create_run(conn, "run_b", org_id=B)
        repo.save_opportunity(conn, _opp(), run_id="run_b", org_id=B)
        secrets.store_api_key(conn, "sk-ant-THEIRS", org_id=B)

        blob = str(repo.shared_funders(conn, org_id=A))

    assert "Open Trust" in blob
    for leak in ("Second Nonprofit", "Community Arts Grant", "sk-ant-THEIRS"):
        assert leak not in blob, f"{leak} must not travel with a shared funder"


def test_you_are_not_offered_your_own_funders_or_ones_you_have(db):
    with session(db) as conn:
        _shared_funder(conn, B, "Shared Trust", "https://example.invalid/dup")
        assert [x["name"] for x in repo.shared_funders(conn, org_id=A)] == ["Shared Trust"]

        # A already has that page under a different name — still the same funder.
        repo.create_funder(conn, {"name": "Same Page, My Name For It",
                                  "url": "https://example.invalid/dup/"}, org_id=A)
        assert repo.shared_funders(conn, org_id=A) == []
        # And B is never shown its own.
        assert repo.shared_funders(conn, org_id=B) == []


def test_two_orgs_offering_the_same_page_appear_once_with_a_count(db):
    """How many nonprofits independently added it is the only trust signal here that
    comes from people rather than from a fetch, and it is worth showing."""
    with session(db) as conn:
        ensure_org(conn, "org_third", "Third")
        _shared_funder(conn, B, "Popular Foundation", "https://example.invalid/pop")
        _shared_funder(conn, "org_third", "Popular Foundation",
                       "https://example.invalid/pop/")

        out = repo.shared_funders(conn, org_id=A)

    assert len(out) == 1
    assert out[0]["added_by_count"] == 2


def test_one_report_hides_it_from_everybody_at_once(db):
    """Deliberately fails towards hiding. Hiding a good funder costs one nonprofit one
    grants page they could add by hand; leaving a bad one up costs somebody an afternoon
    writing to nobody."""
    with session(db) as conn:
        f = _shared_funder(conn, B, "Dubious Fund", "https://example.invalid/d")
        assert repo.shared_funders(conn, org_id=A)

        repo.report_shared_funder(conn, funder_org=B, funder_id=f["id"],
                                  reported_by=A, reason="not a real funder")
        assert repo.shared_funders(conn, org_id=A) == []
        assert len(repo.open_reports(conn)) == 1


def test_reporting_twice_is_one_report_not_a_pattern(db):
    with session(db) as conn:
        f = _shared_funder(conn, B, "Dubious Fund", "https://example.invalid/d")
        first = repo.report_shared_funder(conn, funder_org=B, funder_id=f["id"],
                                          reported_by=A, reason="x")
        again = repo.report_shared_funder(conn, funder_org=B, funder_id=f["id"],
                                          reported_by=A, reason="x")
        assert again["already"] is True and again["report_id"] == first["report_id"]
        assert len(repo.open_reports(conn)) == 1


def test_an_admin_can_take_it_down_for_good_or_put_it_back(db):
    """Both directions matter. Without the restore, one objection permanently removes a
    good funder and a mistake is indistinguishable from moderation."""
    with session(db) as conn:
        f = _shared_funder(conn, B, "Contested Fund", "https://example.invalid/c")
        rid = repo.report_shared_funder(conn, funder_org=B, funder_id=f["id"],
                                        reported_by=A, reason="looks wrong")["report_id"]

        assert repo.resolve_report(conn, rid, uphold=False, by="admin@x") is True
        assert [x["name"] for x in repo.shared_funders(conn, org_id=A)] == ["Contested Fund"]

        rid2 = repo.report_shared_funder(conn, funder_org=B, funder_id=f["id"],
                                         reported_by=A, reason="really")["report_id"]
        assert repo.resolve_report(conn, rid2, uphold=True, by="admin@x") is True
        assert repo.shared_funders(conn, org_id=A) == [], "upheld means gone for good"
        assert repo.open_reports(conn) == []


def test_closing_an_org_keeps_what_it_contributed_and_drops_the_copies(db):
    """The whole point of the asymmetry: a hand-added funder outlives the account, a
    copy of a list we ship does not."""
    from app.db import remove_member

    with session(db) as conn:
        _member(conn, "solo", "only@b.org", B)
        import_starter = __import__("app.db", fromlist=["import_starter_list"])
        import_starter.import_starter_list(conn, "national", B)
        _shared_funder(conn, B, "Their Own Research", "https://example.invalid/own")

        before = {f["name"] for f in repo.list_funders(conn, org_id=B)}
        assert len(before) > 1, "both kinds present to begin with"

        remove_member(conn, "solo", B)

        after = [f for f in repo.list_funders(conn, org_id=B)]
        assert [f["name"] for f in after] == ["Their Own Research"]
        assert [f["added_by"] for f in after] == ["user"]
        # And it is still on offer to everybody else, which is the reason to keep it.
        assert [x["name"] for x in repo.shared_funders(conn, org_id=A)] == \
            ["Their Own Research"]


# --- pause vs block vs delete ---------------------------------------------------
#
# Three actions, and the middle one did not exist. Unticking set `active=0` and "Remove"
# deleted the row, which reads backwards: the reversible thing was hidden in a checkbox
# and the permanent one was a button on every row.

def test_pausing_a_funder_leaves_it_offerable_but_unsearched(db):
    """A pause is seasonal. It must not stop the researched lists mentioning the funder,
    because the org has not said they never want to hear about it."""
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        org = org_for_user(conn, "uid-2", "second@example.org")
        f = repo.create_funder(conn, {"name": "Parker", "url": "https://p.example/g"},
                               org_id=org)
        repo.update_funder(conn, f["id"], {"active": False}, org_id=org)

        assert repo.list_funders(conn, org_id=org, active_only=True) == []
        still_there = repo.list_funders(conn, org_id=org)
        assert len(still_there) == 1 and still_there[0]["blocked"] is False


def test_a_blocked_funder_is_never_searched(db):
    from agent.sources import sources_from_db

    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        org = org_for_user(conn, "uid-2", "second@example.org")
        f = repo.create_funder(conn, {"name": "Parker", "url": "https://p.example/g"},
                               org_id=org)
        repo.update_funder(conn, f["id"], {"blocked": True}, org_id=org)

        assert repo.list_funders(conn, org_id=org, active_only=True) == [], \
            "blocked has to mean unsearched even though `active` is still 1"

    sources, _skipped = sources_from_db(3, [], org_id=org)
    assert [s.funder for s in sources] == [], "the crawl would still have fetched it"


def test_a_blocked_funder_is_not_offered_by_a_researched_list(db):
    """The reason blocking cannot just be `active=0`. Importing a starter list used to
    re-offer anything the org had taken off, every time."""
    from agent.directory import STARTER_LISTS
    from app.db import import_starter_list

    key = STARTER_LISTS[0].key
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        org = org_for_user(conn, "uid-2", "second@example.org")

        import_starter_list(conn, key, org)
        imported = repo.list_funders(conn, org_id=org)
        assert imported, "the fixture list is empty"

        victim = imported[0]
        repo.update_funder(conn, victim["id"], {"blocked": True}, org_id=org)

        before = len(repo.list_funders(conn, org_id=org))
        import_starter_list(conn, key, org)          # import it again
        after = repo.list_funders(conn, org_id=org)

    assert len(after) == before, "a second import added rows"
    blocked_row = next(f for f in after if f["id"] == victim["id"])
    assert blocked_row["blocked"] is True, "the import un-blocked it"


def test_a_blocked_funder_is_not_offered_by_another_nonprofit(db):
    """The other place a funder gets suggested. Blocking is 'stop suggesting this', so
    it has to reach the screen whose whole job is suggesting things."""
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        sharer = org_for_user(conn, "uid-share", "share@example.org")
        me = org_for_user(conn, "uid-me", "me@example.org")

        repo.update_settings(conn, {"share_funders": True}, org_id=sharer)
        theirs = repo.create_funder(
            conn, {"name": "Shared Foundation", "url": "https://shared.example/grants"},
            org_id=sharer)
        conn.execute("UPDATE funders SET check_ok=1, check_note='ok' WHERE id=? AND org_id=?",
                     (theirs["id"], sharer))

        assert [f["name"] for f in repo.shared_funders(conn, org_id=me)] \
            == ["Shared Foundation"], "the precondition: it is on offer"

        mine = repo.create_funder(
            conn, {"name": "Shared Foundation", "url": "https://shared.example/grants"},
            org_id=me)
        repo.update_funder(conn, mine["id"], {"blocked": True}, org_id=me)

        assert repo.shared_funders(conn, org_id=me) == [], \
            "a funder this org blocked came back as somebody else's suggestion"


def test_blocking_reaches_the_indexed_databases_too(db):
    """Same second door the remove list already has: a blocked funder's grants can
    arrive through Grants.gov even though we never fetched their own page."""
    with session(db) as conn:
        org_for_user(conn, "uid-1", "first@example.org")
        org = org_for_user(conn, "uid-2", "second@example.org")
        f = repo.create_funder(conn, {"name": "Parker", "url": "https://p.example/g"},
                               org_id=org)
        repo.update_funder(conn, f["id"], {"blocked": True}, org_id=org)

        assert "parker" in repo.excluded_funder_names(conn, org_id=org)
