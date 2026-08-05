"""The weekly run, and the ways it could fire twice or not at all.

There was no scheduler before this: `Config.run_day = "Wednesday"` sat in a dataclass
nothing read and the dashboard said "every Wednesday night", which nothing enforced. The
only thing that ever started a search was somebody pressing Re-run.

Two failure modes matter, and they pull in opposite directions. Missing a slot costs an
org a week of findings. Firing twice costs them a second run's worth of their own API
credit for results they already have. The tests here are mostly about the second.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import repo                                  # noqa: E402
from app.db import DEFAULT_ORG_ID, ensure_org, init_db, session  # noqa: E402
from app.scheduler import _slot_start, due_orgs, tick  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)
    return path


# --- working out which slot is live -------------------------------------------

def test_the_hour_before_the_slot_still_points_at_last_week():
    """Wednesday 22:00, asked about a 23:00 slot: tonight has not happened yet, so the
    slot that is open is the one from seven days ago."""
    now = datetime(2026, 8, 5, 22, 0, tzinfo=PT)          # a Wednesday
    assert _slot_start(now, "wednesday", 23) == datetime(2026, 7, 29, 23, 0, tzinfo=PT)


def test_the_hour_after_the_slot_points_at_tonight():
    now = datetime(2026, 8, 5, 23, 30, tzinfo=PT)
    assert _slot_start(now, "wednesday", 23) == datetime(2026, 8, 5, 23, 0, tzinfo=PT)


def test_a_missed_slot_is_still_the_live_one_days_later():
    """If the box was down on Wednesday night, Thursday's tick must run the search —
    the org wanted a search this week, not a search at exactly 23:00."""
    now = datetime(2026, 8, 7, 9, 0, tzinfo=PT)           # Friday morning
    assert _slot_start(now, "wednesday", 23) == datetime(2026, 8, 5, 23, 0, tzinfo=PT)


def test_an_unknown_day_falls_back_rather_than_never_running():
    now = datetime(2026, 8, 6, 12, 0, tzinfo=PT)
    assert _slot_start(now, "not-a-day", 23) is not None


# --- who is due ---------------------------------------------------------------

def test_an_org_that_has_never_run_is_due(db):
    with session(db) as conn:
        assert DEFAULT_ORG_ID in due_orgs(conn)


def test_an_org_that_already_ran_this_slot_is_not_due_again(db):
    """The expensive mistake. A second run in one slot spends the org's own credit on
    results they already have."""
    with session(db) as conn:
        repo.create_run(conn, "r1", org_id=DEFAULT_ORG_ID)
        assert due_orgs(conn) == []


def test_a_run_from_before_the_slot_does_not_count(db):
    """Last week's run must not satisfy this week's slot, or an org gets one search and
    then silence."""
    with session(db) as conn:
        repo.create_run(conn, "old", org_id=DEFAULT_ORG_ID)
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute("UPDATE runs SET started_at=? WHERE id='old'", (stale,))
        assert DEFAULT_ORG_ID in due_orgs(conn)


def test_the_kill_switch_stops_scheduling(db):
    """`enabled` is documented as "nothing runs and nothing is spent". A scheduler that
    ignored it would make the switch a lie in the one case it exists for."""
    with session(db) as conn:
        repo.update_settings(conn, {"enabled": False}, org_id=DEFAULT_ORG_ID)
        assert due_orgs(conn) == []


def test_each_org_is_judged_on_its_own_schedule(db):
    with session(db) as conn:
        ensure_org(conn, "org_b", "Second")
        repo.update_settings(conn, {"enabled": False}, org_id="org_b")
        due = due_orgs(conn)

    assert DEFAULT_ORG_ID in due
    assert "org_b" not in due


def test_an_unknown_timezone_does_not_stop_everyone_else(db):
    """A typo in one org's settings field must not take scheduling down for the install."""
    with session(db) as conn:
        ensure_org(conn, "org_b", "Second")
        repo.update_settings(conn, {"schedule_timezone": "Mars/Olympus"}, org_id="org_b")
        due = due_orgs(conn)

    assert DEFAULT_ORG_ID in due
    assert "org_b" in due


# --- and it must not fight the deploy -----------------------------------------

def test_nothing_is_scheduled_while_a_deploy_is_draining(db):
    """Starting a search seconds before `systemctl restart` means it is killed minutes
    later and the org pays for a search it never sees."""
    drain = db.parent / "draining"
    drain.write_text("updating")
    try:
        assert tick() == 0
    finally:
        drain.unlink()
