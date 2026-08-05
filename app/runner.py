"""Runs the pipeline from the dashboard's "Re-run search pipeline" button.

The pipeline is launched as a **subprocess** (`python -m agent.run`), not imported and
called in a thread. Three reasons, in order of how much they matter:

  1. **Stop actually stops.** CLAUDE.md promises the user a kill switch. A thread in
     the middle of an httpx call cannot be interrupted reliably; a process can be
     terminated. The button on the dashboard has to be as real as the config flag.
  2. **It is the same code path as the cron run.** Whatever the org sees on Wednesday
     night is what the button does on Sunday afternoon. A second in-process entrypoint
     would be a second thing to keep correct.
  3. **A crash in the crawl cannot take down the settings page.** The API stays up and
     reports the failure, which is the state the org is most likely to need it in.

The API key is passed to the child through its environment, read from the encrypted
settings row. It is never written to a file, never an argv value (which would put it in
`ps` output for every user on the machine), and never logged.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from . import repo
from .db import db_path, dumps, session
from .secrets import SOURCE_ENVIRONMENT, resolve_api_key

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_LINES = 400

# Lines from the child that mean something to a non-technical reader. Everything else
# (httpx chatter, robots.txt fetches) is kept in the buffer but not surfaced as status.
_INTERESTING = ("✓", "✗", "⚠", "scored", "Crawling", "candidates survived",
                "Archive", "Sources", "dropped", "Budget", "Wrote", "RUN SUMMARY")


class RunManager:
    """One run at a time, across the whole box, and it knows whose run it is.

    The single slot is a budget guard, not a tenancy model: two concurrent runs could
    double-spend one org's ceiling. It is also the main thing standing between this and
    real multi-tenancy, because it means org B waits while org A crawls (FUTURE.md).
    Until a job queue replaces it, the slot at least records its owner, so the dashboard
    can tell "your search is running" from "somebody else's is".
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._run_id: str | None = None
        self._org_id: str | None = None
        self._lines: deque[str] = deque(maxlen=MAX_LOG_LINES)

    # --- state ---------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def current_run_id(self) -> str | None:
        return self._run_id if self.is_running else None

    def current_run_id_for(self, org_id: str) -> str | None:
        """The live run id **if it belongs to this org**, else None.

        Every request-facing caller uses this rather than `current_run_id`, so that one
        org can never see another's log, progress, or Stop button.
        """
        if not self.is_running or self._org_id != org_id:
            return None
        return self._run_id

    def log_tail(self, limit: int = 60) -> list[str]:
        return list(self._lines)[-limit:]

    # --- control -------------------------------------------------------------

    def start(self, *, no_llm: bool = False, budget: float | None = None,
              max_opportunities: int | None = None, org_id: str,
              started_by: str | None = None) -> str:
        with self._lock:
            if self.is_running:
                raise RuntimeError(
                    "A search is already running." if self._org_id == org_id else
                    "Another organization's search is running on this server. "
                    "Searches run one at a time — try again in a few minutes."
                )

            with session() as conn:
                run_id = repo.create_run(conn, org_id=org_id, started_by=started_by)
                repo.update_run(conn, run_id, progress=dumps(
                    {"phase": "starting", "message": "Starting the search…"}))
                key, key_source = resolve_api_key(conn, org_id=org_id)

            cmd = [sys.executable, "-m", "agent.run", "--sink", "db",
                   "--run-id", run_id, "--org-id", org_id]
            if no_llm or not key:
                cmd.append("--no-llm")
            if budget is not None:
                cmd += ["--budget", str(budget)]
            if max_opportunities is not None:
                cmd += ["--max-opportunities", str(max_opportunities)]

            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            env["FUNDWORTHY_DB_PATH"] = str(db_path())
            # Env, not argv: an argv secret is visible in `ps` to every user on the box.
            if key:
                env["ANTHROPIC_API_KEY"] = key
            else:
                env.pop("ANTHROPIC_API_KEY", None)

            self._lines.clear()
            if not key:
                opener = ("Starting the search…  (No API key saved for your "
                          "organization, so this run will not score anything — add one "
                          "on the Settings page.)")
            elif key_source == SOURCE_ENVIRONMENT:
                # Say it out loud. Otherwise a .env on the machine makes the run score
                # while the Settings page shows no key, and the two look contradictory.
                opener = ("Starting the search…  (Using a key from a .env file on this "
                          "computer, not one saved in Settings.)")
            else:
                opener = "Starting the search…"
            self._lines.append(opener)
            self._proc = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            self._run_id = run_id
            self._org_id = org_id

        threading.Thread(target=self._pump, args=(self._proc, run_id),
                         daemon=True, name=f"rise-run-{run_id}").start()
        return run_id

    def stop(self, *, org_id: str | None = None) -> bool:
        """The user's stop button. Terminate, then kill if it will not go.

        `org_id=None` means "stop whatever is running" and is for internal callers only
        (shutdown). A request always passes one, so nobody can stop a run that is not
        theirs — silently, since telling them a run exists is itself a small leak.
        """
        with self._lock:
            if not self.is_running or self._proc is None:
                return False
            if org_id is not None and self._org_id != org_id:
                return False
            proc, run_id = self._proc, self._run_id

        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

        if run_id:
            with session() as conn:
                run = repo.get_run(conn, run_id)
                if run and run["status"] == "running":
                    repo.update_run(conn, run_id, status="stopped",
                                    stop_reason="stopped_by_user")
        self._lines.append("Stopped by you.")
        return True

    # --- output --------------------------------------------------------------

    def _pump(self, proc: subprocess.Popen, run_id: str) -> None:
        """Drain the child's output into the ring buffer and the run row."""
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self._lines.append(line)
                if any(token in line for token in _INTERESTING):
                    self._write_progress(run_id, line)
        except Exception as exc:  # noqa: BLE001
            log.warning("run %s: output pump failed (%s)", run_id, exc)
        finally:
            code = proc.wait()
            self._finalize(run_id, code)

    def _write_progress(self, run_id: str, message: str) -> None:
        try:
            with session() as conn:
                repo.update_run(conn, run_id, progress=dumps(
                    {"phase": "running", "message": message[:300]}))
        except Exception as exc:  # noqa: BLE001 — progress is cosmetic, never fatal
            log.debug("could not write progress for %s: %s", run_id, exc)

    def _finalize(self, run_id: str, code: int) -> None:
        """The agent writes its own run row through the sink. This only has to catch
        the cases where it could not: a crash, or a stop before the sink ran.

        A NEGATIVE exit code means the process was killed by a signal, which for this
        app means the Stop button — `stop()` sends SIGTERM. That is not a failure, and
        it raced: the pump thread got here before stop() could mark the row, so a run
        the user deliberately ended reported "failed (exit -15)". Deciding it here, from
        the exit code itself, removes the race rather than papering over it.
        """
        stopped = code < 0
        try:
            with session() as conn:
                run = repo.get_run(conn, run_id)
                if run and run["status"] == "running":
                    status = "done" if code == 0 else ("stopped" if stopped else "failed")
                    message = ("Finished." if code == 0 else
                               "Stopped by you." if stopped else
                               f"The search failed (exit {code}). The log below says why.")
                    repo.update_run(
                        conn, run_id,
                        status=status,
                        stop_reason=run["stop_reason"] or (
                            None if code == 0 else
                            "stopped_by_user" if stopped else f"exit_{code}"),
                        progress=dumps({"phase": status, "message": message}),
                    )
                elif run:
                    repo.update_run(conn, run_id, progress=dumps(
                        {"phase": "done", "message": "Finished."}))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not finalize run %s: %s", run_id, exc)
        log.info("run %s finished with exit code %s", run_id, code)


MANAGER = RunManager()
