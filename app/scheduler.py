"""The weekly run, per org, on the day and hour they chose.

There was no scheduler before this. `Config.run_day = "Wednesday"` sat in a dataclass
nothing read, the dashboard said "it searches every Wednesday night", and the only thing
that ever started a search was somebody pressing Re-run. The sentence in the UI was the
whole feature.

**It runs inside the API process**, as a background thread, rather than as a systemd
timer calling `python -m agent.run`. That is the unusual choice, so here is why:

  - `RunManager` is the one place that knows how many runs are already going, whether a
    deploy is draining, and whether this org has spent its month. A timer launching the
    pipeline directly would bypass all three — and the first thing it would do wrong is
    start a run during a deploy, which is exactly what the drain gate exists to stop.
  - Under BYO-key a scheduled run has to resolve *each org's* key from the database.
    `RunManager.start` already does. A global cron run would use whatever
    `ANTHROPIC_API_KEY` happens to be in the VM's `.env` — one org's key paying for
    everybody's searches, which is the bug this codebase spent a week removing.
  - A handful of orgs on one small VM does not need a job queue, and pretending otherwise
    would mean running Redis to schedule three searches a week.

The cost is that scheduling stops if the process is down, and that a second uvicorn
worker would double-fire. Both are the same limitation `RunManager` already has, and both
are fixed by the same thing: a real queue with run state in the database (FUTURE.md).

**Missing a slot is not an error.** If the box was down at 23:00 Wednesday, the run
happens at the next tick — the org wanted a search this week, not a search at exactly
that minute. What must never happen is two searches for one slot, so a run is recorded
against the week it was scheduled for, not the moment it started.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import repo
from .db import session
from .runner import MANAGER, draining

log = logging.getLogger(__name__)

# How often to look. Five minutes is far finer than the hour anyone schedules to, and
# coarse enough that the check costs nothing — it is one indexed query per org.
TICK_SECONDS = 300

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _local_now(tz_name: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        # A timezone the box does not know is a typo in a settings field, not a reason to
        # stop scheduling for everybody. UTC is wrong by hours; silence is wrong by a week.
        log.warning("unknown timezone %r — scheduling that org in UTC", tz_name)
        return datetime.now(timezone.utc)


def _slot_start(now: datetime, day: str, hour: int) -> datetime | None:
    """The most recent moment this org's slot opened, or None if it has not yet this week.

    Anchoring to the slot rather than to "now minus seven days" is what makes a missed
    Wednesday run on Thursday instead of silently waiting a week, while still counting
    as *Wednesday's* run — so catching up cannot turn into running twice.
    """
    try:
        want = DAYS.index(day.strip().lower())
    except ValueError:
        want = DAYS.index("wednesday")

    days_since = (now.weekday() - want) % 7
    slot = (now - timedelta(days=days_since)).replace(
        hour=max(0, min(23, hour)), minute=0, second=0, microsecond=0)
    if slot > now:
        # Today is the day but the hour has not arrived; last week's slot is the live one.
        slot -= timedelta(days=7)
    return slot


def due_orgs(conn, now_utc: datetime | None = None) -> list[str]:
    """Orgs whose slot has opened and which have not run since it did."""
    now_utc = now_utc or datetime.now(timezone.utc)
    out: list[str] = []

    for row in conn.execute("SELECT id FROM orgs"):
        org_id = row["id"]
        settings = repo.get_settings(conn, org_id=org_id)
        if not settings["enabled"]:
            continue                      # the kill switch, and it is the whole answer
        if not settings["schedule_enabled"]:
            # They have not asked for an unattended weekly search, which is the default.
            # Distinct from the kill switch above: this org is using Fundworthy happily,
            # by hand, and nothing should start spending their credit at 11pm because a
            # `schedule_day` column has a value in it. Every org has one — it is the
            # starting point the picker opens on, not a decision anybody made.
            continue

        local = _local_now(str(settings["schedule_timezone"]))
        if local.tzinfo != timezone.utc:
            now_here = local
        else:
            now_here = now_utc

        slot = _slot_start(now_here, str(settings["schedule_day"]),
                           int(settings["schedule_hour"]))
        if slot is None:
            continue

        last = conn.execute(
            "SELECT started_at FROM runs WHERE org_id=? ORDER BY started_at DESC LIMIT 1",
            (org_id,)).fetchone()
        if last and last["started_at"]:
            try:
                started = datetime.fromisoformat(last["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started >= slot.astimezone(timezone.utc):
                    continue              # this slot is already served
            except ValueError:
                pass                      # unparseable timestamp — treat as no run

        out.append(org_id)
    return out


def tick() -> int:
    """One pass. Returns how many runs were started."""
    if draining():
        # A deploy is in progress. Starting a search now means it is killed minutes
        # later, and the org pays for a search it never sees.
        log.info("scheduler: skipping this tick, a deploy is draining")
        return 0

    started = 0
    with session() as conn:
        candidates = due_orgs(conn)

    for org_id in candidates:
        try:
            run_id = MANAGER.start(org_id=org_id, trigger="scheduled")
            log.info("scheduler: started %s for org %s", run_id, org_id)
            started += 1
        except RuntimeError as exc:
            # Already running, at the concurrency ceiling, or over the month's budget.
            # All three are "not now", not "not ever" — the next tick tries again, and
            # the slot stays open until something actually runs.
            log.info("scheduler: not starting org %s — %s", org_id, exc)
        except Exception:  # noqa: BLE001
            log.exception("scheduler: could not start a run for org %s", org_id)
    return started


def start(stop: threading.Event | None = None) -> threading.Thread:
    """Run `tick` forever on a daemon thread. Called once from the app's lifespan."""
    stop = stop or threading.Event()

    def loop() -> None:
        log.info("scheduler: running, every %d seconds", TICK_SECONDS)
        while not stop.wait(TICK_SECONDS):
            try:
                tick()
            except Exception:  # noqa: BLE001 — a bad tick must not end scheduling
                log.exception("scheduler: tick failed")

    thread = threading.Thread(target=loop, daemon=True, name="fundworthy-scheduler")
    thread.start()
    return thread
