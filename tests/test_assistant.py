"""The program-card assistant's prompt. Offline — content locks only, no API key.

    .venv/bin/python -m pytest tests/test_assistant.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_search_queries_are_told_to_vary_their_angle():
    """Found auditing a real run (2026-08-09): all three of an org's real cards
    generated near-identical query shapes — "grants for X" / "funders supporting X" /
    "foundations funding X" — that differed only in the topic noun-phrase, with no
    query aimed at a different kind of funder or a different angle on the same
    program. The instruction used to constrain a single query's specificity but said
    nothing about variety across the 3-5, which is what actually produced the
    repetition."""
    from app.assistant import SYSTEM

    assert "vary the angle" in SYSTEM.lower()
    assert "other programs" in SYSTEM.lower(), \
        "must warn against a query that would fit any of the org's other programs too"
