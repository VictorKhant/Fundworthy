"""The technical log has to outlive the process that produced it.

CLAUDE.md calls the log "still the only thing that explains a run that died halfway", and
until v16 it was a `deque` on an in-process slot that `_pump` deletes in the same `finally`
block that reaps the child. So for every finished run — which is every run somebody
actually wants to read the log for — "Show the technical log" opened onto nothing.

Offline: `_persist_log` is driven directly against a real database with a fake slot, so
there is no subprocess and nothing to spend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import repo  # noqa: E402
from app.db import DEFAULT_ORG_ID, init_db, session  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "rise.db"
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(path))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    init_db(path)
    return path


def _slot(run_id: str, lines):
    """The two fields `_persist_log` touches, without a subprocess behind them."""
    from collections import deque

    from app.runner import MAX_LOG_LINES

    return type("S", (), {"run_id": run_id, "lines": deque(lines, maxlen=MAX_LOG_LINES)})()


def test_the_log_is_written_to_the_run_row(db):
    import app.runner as runner

    with session(db) as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)

    runner.RunManager()._persist_log(_slot(run_id, ["✓ Some Foundation", "✗ Another one"]))

    with session(db) as conn:
        run = repo.get_run(conn, run_id, org_id=DEFAULT_ORG_ID)
    assert run["log_tail"] == ["✓ Some Foundation", "✗ Another one"], (
        "the log did not survive the run"
    )


def test_only_the_tail_is_kept_because_the_reason_is_at_the_end(db):
    """A five-minute crawl's whole output is not something to hand to every request. The
    cap keeps the END, because that is where a failure is."""
    import app.runner as runner
    from app.runner import PERSISTED_LOG_LINES

    with session(db) as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)

    lines = [f"line {i}" for i in range(PERSISTED_LOG_LINES + 250)]
    runner.RunManager()._persist_log(_slot(run_id, lines))

    with session(db) as conn:
        kept = repo.get_run(conn, run_id, org_id=DEFAULT_ORG_ID)["log_tail"]

    assert len(kept) == PERSISTED_LOG_LINES
    assert kept[-1] == lines[-1], "the last line — where the error is — must be kept"


def test_a_run_that_kept_no_log_reads_back_as_empty_not_null(db):
    """Old rows predate the column. They have to read back as a list so the UI can say
    "no log was kept" rather than crashing on a null."""
    with session(db) as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)
        assert repo.get_run(conn, run_id, org_id=DEFAULT_ORG_ID)["log_tail"] == []


def test_persisting_a_log_never_breaks_a_run(db, monkeypatch):
    """Best-effort, like every other cosmetic write this thread does. A lost transcript
    must never be the thing that fails a search."""
    import app.runner as runner

    def explode(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(runner.repo, "update_run", explode)
    # No raise.
    runner.RunManager()._persist_log(_slot("nope", ["a line"]))


def test_the_log_survives_to_the_api_once_the_live_buffer_is_gone(db, monkeypatch):
    """The end-to-end shape: `GET /api/runs/current` returns the live buffer while a run
    is going and the persisted tail afterwards. Before this, `MANAGER.log_tail()` returned
    `[]` the moment the slot was reaped and the endpoint had nothing else to offer."""
    from fastapi.testclient import TestClient

    import app.main as main

    with session(db) as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)
        repo.update_run(conn, run_id, status="done", log_tail=["✗ it failed here"])

    # Nothing running, so the live buffer is empty — exactly the finished-run case.
    monkeypatch.setattr(main.MANAGER, "current_run_id_for", lambda org: None)
    monkeypatch.setattr(main.MANAGER, "log_tail", lambda org, limit=60: [])

    client = TestClient(main.create_app())
    body = client.get("/api/runs/current").json()

    assert body["running"] is False
    assert body["log"] == ["✗ it failed here"], (
        "the endpoint fell back to an empty live buffer instead of the stored log"
    )


def test_the_log_is_not_on_the_hot_state_path(db):
    """`/api/state` is fetched on every dashboard load and almost nobody opens the log,
    so it rides on its own endpoint — same reasoning as `rejects`."""
    from fastapi.testclient import TestClient

    import app.main as main

    with session(db) as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)
        repo.update_run(conn, run_id, status="done",
                        log_tail=["a" * 200] * 200, rejects=[])

    client = TestClient(main.create_app())
    latest = client.get("/api/state").json()["latest_run"]

    assert latest is not None
    assert "log_tail" not in latest, "200 lines of log on every dashboard load"
    assert "rejects" not in latest
