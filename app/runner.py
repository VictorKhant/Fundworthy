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
from agent.score import SPEND_MARKER, STAGE_MARKER
from .db import db_path, dumps, loads, session
from .secrets import SOURCE_ENVIRONMENT, resolve_api_key

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_LINES = 400

# How many orgs may crawl at once. Not a tenancy rule — a machine guard. Each run is a
# subprocess doing HTTP and HTML parsing, and the target box is a 2-4 core free-tier VM.
# Raise it on a bigger machine; replace the whole thing with a job queue past a handful
# of orgs (FUTURE.md).
MAX_CONCURRENT_RUNS = int(os.environ.get("FUNDWORTHY_MAX_CONCURRENT_RUNS", "3"))

# Searches per org per rolling day. **Off by default (0 = unlimited)**, and that is a
# deliberate reversal.
#
# It shipped at 12, which was wrong: an org runs searches on its own Anthropic key, so
# how many it wants is its own business and its own bill. A ceiling on that is us
# rationing something we do not pay for.
#
# The concern behind it was real but aimed at the wrong target — an org with *no* key can
# still make the server fetch funders' pages for free, and the monthly spend cap cannot
# bound a run that costs nothing. That is load on the box and traffic at funders' sites,
# not the org's money, and it is already bounded by MAX_CONCURRENT_RUNS; the proper fix
# is the shared fetch cache in FUTURE.md. So this stays as a lever an operator can reach
# for if one account genuinely misbehaves, and stays out of the way otherwise.
MAX_RUNS_PER_DAY = int(os.environ.get("FUNDWORTHY_MAX_RUNS_PER_DAY", "0"))

# A deploy touches this file, waits for in-flight runs to finish, restarts, and removes
# it. While it exists, new runs are refused — otherwise a run started thirty seconds
# before `systemctl restart` gets killed at minute seven, and the org pays for a search
# it never sees. A file rather than a setting so the deploy script can create it over SSH
# without going through the API (which is about to be restarted anyway).
DRAIN_FILE = "draining"


def draining() -> bool:
    return (db_path().parent / DRAIN_FILE).exists()


def preflight(conn, *, org_id: str, no_llm: bool = False) -> list[dict]:
    """Why a search cannot usefully start right now, in words the user can act on.

    Empty list means go. Everything in it is knowable *before* the first HTTP request,
    and every entry names the page that fixes it.

    Three of the four reasons a search comes back empty were previously only
    discoverable by running one: press Search, wait five to ten minutes while the crawler
    politely walks every funder's website, and get back a blank list with nothing on it
    to explain itself. No key, no funders, nothing ticked — all three are a database read
    away, and none of them is the user's fault for not knowing.

    **One function, two callers, so the two can never disagree.** `RunManager.start`
    refuses on it, and `GET /api/state` returns it so the button is disabled with the
    same sentence rather than a differently-worded one. A disabled button that says one
    thing and an error that says another is how a person concludes the app is broken.

    Each entry is `{code, message, page}`. `page` is a dashboard section name, so the UI
    can offer to take them there instead of describing where to go.
    """
    from agent.config import max_tier_for
    from agent.sources import sources_from_db

    from .secrets import resolve_api_key

    out: list[dict] = []
    settings = repo.get_settings(conn, org_id=org_id)

    if not settings["enabled"]:
        out.append({
            "code": "disabled",
            "message": (
                "Fundworthy is switched off, so nothing will run and nothing will be "
                'spent. Turn it back on under "Adjust search settings" on This week.'
            ),
            "page": "dashboard",
        })

    # `no_llm` is the deliberate free-crawl mode, which genuinely does not need a key.
    # Nothing in the dashboard sends it; it exists for the CLI and for tests.
    if not no_llm and not resolve_api_key(conn, org_id=org_id)[0]:
        out.append({
            "code": "no_api_key",
            "message": (
                "Fundworthy has no Claude API key to read funder pages with, so a "
                "search would find nothing. Open Settings and paste your own key — a "
                "weekly search costs about a dollar, billed to you and nobody else."
            ),
            "page": "settings",
        })

    if not repo.list_programs(conn, org_id=org_id, active_only=True):
        out.append({
            "code": "no_programs",
            "message": (
                "No program is ticked, so there is nothing to search for. Tick at least "
                'one card under "Your programs" at the bottom of This week — that is '
                "how Fundworthy knows which grants are worth your time."
            ),
            "page": "dashboard",
        })

    active = conn.execute(
        "SELECT COUNT(*) AS n FROM funders WHERE org_id=? AND active=1",
        (org_id,)).fetchone()["n"]
    if not active:
        out.append({
            "code": "no_funders",
            "message": (
                "Your funder list is empty, and that list is the only thing Fundworthy "
                "searches — it reads the funders you put on it and nowhere else. Open "
                "Discover funders and add at least one; the researched lists go on with "
                "a single click."
            ),
            "page": "discover",
        })

    # A "your funders do not match the ticked sectors" refusal used to follow, for the
    # case where the list was non-empty but the sector filter excluded all of it. It is
    # gone with that filter (R8): the funder list is no longer narrowed by sector, so a
    # funder on the list is a funder that gets fetched, and the state cannot arise. The
    # empty-list refusal above still covers the one that can.

    return out


def drain_notice() -> str:
    """What the deploy left in the drain file, for the banner. Empty when not draining.

    Read by a **public** endpoint, so it must never say anything but "we are updating".
    The deploy writes it; nothing in the app does.
    """
    path = db_path().parent / DRAIN_FILE
    try:
        return path.read_text(encoding="utf-8").strip()[:200]
    except OSError:
        return ""

# Lines from the child that mean something to a non-technical reader. Everything else
# (httpx chatter, robots.txt fetches) is kept in the buffer but not surfaced as status.
def _spend_from(line: str) -> float | None:
    """Pull the running total out of a `::spend 0.041234` marker, or return None.

    Tolerant on purpose — a malformed marker is a cosmetic loss, and raising here would
    take down the thread draining the child's output.
    """
    marker = SPEND_MARKER.strip()
    if marker not in line:
        return None
    try:
        return float(line.rsplit(marker, 1)[1].strip().split()[0])
    except (IndexError, ValueError):
        return None


def _funnel_from(line: str) -> dict | None:
    """Pull the live funnel out of a `::stage {"parsed":214,…}` marker, or return None.

    Tolerant for the same reason as `_spend_from`: this drives three progress bars, and
    a malformed marker should cost a frame of animation rather than the thread draining
    the child's output.
    """
    marker = STAGE_MARKER.strip()
    if marker not in line:
        return None
    try:
        value = loads(line.rsplit(marker, 1)[1].strip(), None)
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, dict) else None


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
    # The live funnel from the child's `::stage` markers, so every write to `progress`
    # carries the latest one. Only `_pump` touches it, and there is exactly one pump
    # thread per slot, so the two writers below cannot race each other.
    funnel: dict = field(default_factory=dict)

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
                today = repo.runs_today(conn, org_id=org_id) if MAX_RUNS_PER_DAY else 0
                if MAX_RUNS_PER_DAY and today >= MAX_RUNS_PER_DAY:
                    raise RuntimeError(
                        f"Your organization has already run {today} searches today. "
                        "Fundworthy is built around one search a week — try again "
                        "tomorrow, or get in touch if you genuinely need more."
                    )

                spend = repo.spend_summary(conn, org_id=org_id)
                if spend["over_cap"]:
                    raise RuntimeError(
                        f"Your organization has used its ${spend['cap_usd']:.2f} monthly "
                        f"limit for {spend['month']} (${spend['spent_usd']:.2f} spent). "
                        "Raise the limit on the Settings page, or wait for next month."
                    )

                # Last, and deliberately: everything above answers "may this org run
                # now", and those answers are more specific. An org that has spent its
                # month should be told that, not sent to Settings to add a key it may
                # well already have. This one answers "would running accomplish
                # anything", and it is the only refusal here that survives waiting.
                stoppers = preflight(conn, org_id=org_id, no_llm=no_llm)
                if stoppers:
                    raise RuntimeError(stoppers[0]["message"])

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
                # Only reachable when the caller asked for --no-llm on purpose:
                # `preflight` refuses an ordinary keyless run above, rather than letting
                # it crawl for ten minutes and score nothing.
                opener = ("Starting the search…  (Free mode: pages will be found and "
                          "filtered, but nothing will be read or scored.)")
            elif key_source == SOURCE_ENVIRONMENT:
                # Local installs only — see `secrets.resolve_api_key`. Said out loud even
                # so: otherwise a .env on the machine makes the run score while the
                # Settings page shows no key, and the two look contradictory.
                opener = ("Starting the search…  (Local install: reading with the "
                          "ANTHROPIC_API_KEY from this machine's .env, because none is "
                          "saved in Settings.)")
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
                # The running spend total, emitted by Budget.record after every call.
                # Consumed and dropped: it is machine chatter, and a log full of
                # "::spend 0.0421" is worse than the delay it fixes.
                spend = _spend_from(line)
                if spend is not None:
                    self._write_spend(slot.run_id, spend)
                    continue
                # The funnel behind the three stage boxes. Same deal: consumed and
                # dropped, because `::stage {"parsed":214,…}` in the middle of the log
                # is exactly the machine chatter the boxes exist to replace.
                funnel = _funnel_from(line)
                if funnel is not None:
                    slot.funnel = funnel
                    self._write_funnel(slot)
                    continue
                slot.lines.append(line)
                if any(token in line for token in _INTERESTING):
                    self._write_progress(slot, line)
        except Exception as exc:  # noqa: BLE001
            log.warning("run %s: output pump failed (%s)", slot.run_id, exc)
        finally:
            code = slot.proc.wait()
            self._finalize(slot.run_id, code)
            with self._lock:
                if self._slots.get(slot.org_id) is slot:
                    del self._slots[slot.org_id]

    def _write_spend(self, run_id: str, spent: float) -> None:
        """The live figure the status strip reads, written straight onto the run row.

        Best-effort like `_write_progress`: a search must not die because one cosmetic
        write lost a race with the sink.
        """
        try:
            with session() as conn:
                repo.update_run(conn, run_id, usd_spent=round(spent, 6))
        except Exception as exc:  # noqa: BLE001
            log.debug("could not write live spend for %s: %s", run_id, exc)

    def _write_funnel(self, slot: "_Slot") -> None:
        """The three counters onto their own columns, and the denominators into
        `progress`.

        `candidates_parsed`, `triaged` and `scored` are real columns the finished run
        already fills, so writing them as the run goes means the stage boxes read the
        same fields live that they read afterwards — one shape of data, not two.

        `survivors` and `kept` have nowhere of their own and do not want a migration for
        something that is meaningless the moment the run ends. They ride in the progress
        JSON, which is already free-form and already this thread's to write.
        """
        try:
            with session() as conn:
                repo.update_run(
                    conn, slot.run_id,
                    candidates_parsed=int(slot.funnel.get("parsed", 0)),
                    triaged=int(slot.funnel.get("triaged", 0)),
                    scored=int(slot.funnel.get("scored", 0)),
                    progress=dumps({"phase": "running",
                                    "message": slot.lines[-1] if slot.lines else "",
                                    "funnel": slot.funnel}),
                )
        except Exception as exc:  # noqa: BLE001 — a stalled bar, never a dead run
            log.debug("could not write funnel for %s: %s", slot.run_id, exc)

    def _write_progress(self, slot: "_Slot", message: str) -> None:
        try:
            with session() as conn:
                repo.update_run(conn, slot.run_id, progress=dumps(
                    {"phase": "running", "message": message[:300],
                     # Carried, not dropped. Both writers land on the same column, and
                     # without this every interesting log line would blank the funnel
                     # and the bars would flicker back to zero between candidates.
                     "funnel": slot.funnel}))
        except Exception as exc:  # noqa: BLE001 — progress is cosmetic, never fatal
            log.debug("could not write progress for %s: %s", slot.run_id, exc)

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
