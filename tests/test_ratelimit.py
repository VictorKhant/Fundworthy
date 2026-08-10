"""app/ratelimit.py: the per-key, per-minute cap behind POST /api/runs and
POST /api/programs/draft (FUTURE.md P1). Offline, no time.sleep — the window is
exercised by monkeypatching time.monotonic rather than waiting on the clock.

    .venv/bin/python -m pytest tests/test_ratelimit.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ratelimit  # noqa: E402


def test_allows_up_to_the_limit_then_refuses():
    ratelimit._hits.clear()
    for _ in range(3):
        assert ratelimit.check("k", limit=3) is True
    assert ratelimit.check("k", limit=3) is False


def test_different_keys_do_not_share_a_budget():
    """The org-isolation rule this app enforces everywhere else, applied to the one
    piece of state that lives outside the database: one org hammering the endpoint
    must not cost another org anything."""
    ratelimit._hits.clear()
    for _ in range(3):
        assert ratelimit.check("org-a", limit=3) is True
    assert ratelimit.check("org-a", limit=3) is False
    assert ratelimit.check("org-b", limit=3) is True


def test_the_window_expires_hits_rather_than_banning_forever(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    ratelimit._hits.clear()

    for _ in range(2):
        assert ratelimit.check("k", limit=2, window_seconds=60) is True
    assert ratelimit.check("k", limit=2, window_seconds=60) is False

    now[0] += 61  # past the window
    assert ratelimit.check("k", limit=2, window_seconds=60) is True


def test_an_old_hit_ages_out_without_evicting_a_recent_one(monkeypatch):
    """Not a fixed calendar window — a genuinely sliding one, the same distinction
    CLAUDE.md makes for the bug-report cap (`count_recent_bug_reports`'s own docstring)
    between a rolling window and a reset-at-midnight one."""
    now = [0.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    ratelimit._hits.clear()

    assert ratelimit.check("k", limit=2, window_seconds=10) is True   # t=0
    now[0] = 9
    assert ratelimit.check("k", limit=2, window_seconds=10) is True   # t=9, still in window
    now[0] = 11
    # t=0 has aged out (11 - 0 > 10); t=9 has not (11 - 9 < 10) — one slot free, not two.
    assert ratelimit.check("k", limit=2, window_seconds=10) is True
    assert ratelimit.check("k", limit=2, window_seconds=10) is False
