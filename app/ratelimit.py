"""A per-key, per-minute request cap. (FUTURE.md P1)

`POST /api/runs` and `POST /api/programs/draft` had no rate limit at all, only the
guards that stop what happens *after* the request lands: `RunManager` refuses a second
concurrent run for the same org, and `runner.preflight` refuses one that could not
work. Neither stops a script from simply making the request at any rate the network
allows. For `/runs` that is mostly wasted CPU on a box with exactly one to spare — the
existing guards mean nothing expensive actually happens. For `/programs/draft` it is
real money: every call fetches a page and makes a Sonnet call (up to the $0.10 ceiling
in `app/assistant.py`) regardless of whether it succeeds, and nothing upstream of this
module bounds how often one org can call it.

In-process and not database-backed, on purpose. This app is already single-process by
design — `RunManager` is an in-process singleton, and FUTURE.md's own scale section
names a real job queue, not this, as what would let it run behind more than one uvicorn
worker. A count that resets when the process restarts is the right behavior for a rate
limit (nobody wants a deploy to leave an org locked out), not a gap in it.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, *, limit: int, window_seconds: float = 60.0) -> bool:
    """Record one attempt under `key` and say whether it was within the limit.

    A fixed sliding window: `hits` older than `window_seconds` age out on every call,
    so this is memory-bounded per key without a separate cleanup pass — a key nobody
    has hit recently costs nothing to keep around.
    """
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True
