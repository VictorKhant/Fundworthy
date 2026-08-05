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
from dataclasses import dataclass, field
from pathlib import Path

from . import repo
from .db import db_path, dumps, session
from .secrets import SOURCE_ENVIRONMENT, resolve_api_key

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_LINES = 400

# How many orgs may crawl at once. Not a tenancy rule — a machine guard. Each run is a
# subprocess doing HTTP and HTML parsing, and the target box is a 2-4 core free-tier VM.
# Raise it on a bigger machine; replace the whole thing with a job queue past a handful
# of orgs (FUTURE.md).
MAX_CONCURRENT_RUNS = int(os.environ.get("FUNDWORTHY_MAX_CONCURRENT_RUNS", "3"))

# A deploy touches this file, waits for in-flight runs to finish, restarts, and removes
# it. While it exists, new runs are refused — otherwise a run started thirty seconds
# before `systemctl restart` gets killed at minute seven, and the org pays for a search
# it never sees. A file rather than a setting so the deploy script can create it over SSH
# without going through the API (which is about to be restarted anyway).
DRAIN_FILE = "draining"


def draining() -> bool:
    return (db_path().parent / DRAIN_FILE).exists()

# Lines from the child that mean something to a non-technical reader. Everything else
# (httpx chatter, robots.txt fetches) is kept in the buffer but not surfaced as status.
_INTERESTING = ("✓", "✗", "⚠", "scored", "Crawling", "candidates survived",
                "Archive", "Sources", "dropped", "Budget", "Wrote", "RUN SUMMARY")


@dataclass
class _Slot:
    """One org's in-flight run. Its log lives here, not in the manager, so two orgs
    crawling at once cannot interleave their output into one buffer."""
    proc: subprocess.Popen
    run_id: str
    org_id: str
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None


class RunManager:
    """One run at a time **per org**, several orgs at once.

    This used to be one run at a time across the whole box, and the reason was sound
    while it lasted: with a single shared Anthropic key there was a single shared budget,
    so two concurrent runs really could double-spend one $1 ceiling.

    Per-org keys removed that. Two orgs now spend different money against different rate
    limits, so making one wait for the other buys nothing and costs them a week — the
    weekly run is the product. What survives is the part that was always about one org:
    a second run for the *same* org would double-spend that org's budget, so each org
    still gets exactly one slot. Double-clicking Re-run is still refused; another
    nonprofit's crawl no longer blocks yours.

    `MAX_CONCURRENT_RUNS` is a machine guard, not a tenancy rule: each run is a Python
    subprocess doing HTTP and parsing on a small free-tier VM, and unbounded fan-out
    would take the API down with it. Past a handful of orgs this whole class should
    become a real job queue (FUTURE.md).
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_RUNS) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {}
        self._max_concurrent = max_concurrent

    # --- state ---------------------------------------------------------------

    def _reap(self) -> None:
        """Drop finished slots. Called under the lock by everything that reads state."""
        for org_id in [o for o, s in self._slots.items() if not s.alive]:
            del self._slots[org_id]

    @property
    def is_running(self) -> bool:
        """Is anything running at all. Ops and shutdown only — a request must never use
        this to decide what to show a user; use `current_run_id_for`."""
        with self._lock:
            self._reap()
            return bool(self._slots)

    @property
    def active_count(self) -> int:
        with self._lock:
            self._reap()
            return len(self._slots)

    def current_run_id_for(self, org_id: str) -> str | None:
        """The live run id for this org, or None. Every request-facing caller uses this,
        so one org can never see another's log, progress, or Stop button."""
        with self._lock:
            self._reap()
            slot = self._slots.get(org_id)
            return slot.run_id if slot else None

    def log_tail(self, org_id: str, limit: int = 60) -> list[str]:
        with self._lock:
            slot = self._slots.get(org_id)
            return list(slot.lines)[-limit:] if slot else []

    # --- control -------------------------------------------------------------

    def start(self, *, no_llm: bool = False, budget: float | None = None,
              max_opportunities: int | None = None, org_id: str,
              started_by: str | None = None) -> str:
        if draining():
            raise RuntimeError(
                "Fundworthy is being updated right now, so new searches are paused for "
                "a few minutes. Nothing is lost — try again shortly."
            )

        with self._lock:
            self._reap()
            if org_id in self._slots:
                raise RuntimeError("A search is already running for your organization.")
            if len(self._slots) >= self._max_concurrent:
                raise RuntimeError(
                    "The server is running as many searches as it can handle right now. "
                    "Yours will start if you try again in a few minutes."
                )

            with session() as conn:
                # The month's ceiling, checked before anything is spent rather than
                # after. `run_budget_usd` bounds one run; without this an org could
                # press Re-run all afternoon and each run would pass its own check.
                spend = repo.spend_summary(conn, org_id=org_id)
                if spend["over_cap"]:
                    raise RuntimeError(
                        f"Your organization has used its ${spend['cap_usd']:.2f} monthly "
                        f"limit for {spend['month']} (${spend['spent_usd']:.2f} spent). "
                        "Raise the limit on the Settings page, or wait for next month."
                    )

                run_id = repo.create_run(conn, org_id=org_id, started_by=started_by)
                repo.update_run(conn, run_id, progress=dumps(
                    {"phase": "starting", "message": "Starting the search…"}))
                key, key_source = resolve_api_key(conn, org_id=org_id)

                # Never let one run overshoot what is left in the month. A $1 run with
                # $0.40 of headroom becomes a $0.40 run, not a $1 overspend.
                headroom = spend["remaining_usd"]
                ceiling = float(repo.get_settings(conn, org_id=org_id)["run_budget_usd"])
                effective = min(budget if budget is not None else ceiling, headroom)
                if effective < (budget if budget is not None else ceiling):
                    log.info("run %s capped at $%.2f by the monthly limit", run_id,
                             effective)
                budget = round(effective, 4)

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

            proc = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            slot = _Slot(proc=proc, run_id=run_id, org_id=org_id)
            slot.lines.append(opener)
            self._slots[org_id] = slot

        threading.Thread(target=self._pump, args=(slot,),
                         daemon=True, name=f"fundworthy-run-{run_id}").start()
        return run_id

    def stop(self, *, org_id: str | None = None) -> bool:
        """The user's stop button. Terminate, then kill if it will not go.

        `org_id=None` stops everything and is for shutdown only. A request always passes
        one, so nobody can stop a run that is not theirs — and it returns False rather
        than saying "that isn't yours", since confirming a run exists is itself a leak.
        """
        with self._lock:
            self._reap()
            targets = ([self._slots[org_id]] if org_id in self._slots
                       else [] if org_id is not None else list(self._slots.values()))
        if not targets:
            return False

        for slot in targets:
            slot.proc.terminate()
            try:
                slot.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                slot.proc.kill()
                slot.proc.wait(timeout=5)

            with session() as conn:
                run = repo.get_run(conn, slot.run_id)
                if run and run["status"] == "running":
                    repo.update_run(conn, slot.run_id, status="stopped",
                                    stop_reason="stopped_by_user")
            slot.lines.append("Stopped by you.")
        return True

    # --- output --------------------------------------------------------------

    def _pump(self, slot: "_Slot") -> None:
        """Drain one child's output into its own slot's buffer and the run row."""
        assert slot.proc.stdout is not None
        try:
            for raw in slot.proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                slot.lines.append(line)
                if any(token in line for token in _INTERESTING):
                    self._write_progress(slot.run_id, line)
        except Exception as exc:  # noqa: BLE001
            log.warning("run %s: output pump failed (%s)", slot.run_id, exc)
        finally:
            code = slot.proc.wait()
            self._finalize(slot.run_id, code)
            with self._lock:
                if self._slots.get(slot.org_id) is slot:
                    del self._slots[slot.org_id]

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
