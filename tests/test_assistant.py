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
    from app.assistant import _system

    system = _system()
    assert "vary the angle" in system.lower()
    assert "other programs" in system.lower(), \
        "must warn against a query that would fit any of the org's other programs too"


# --- the San Diego leak (FUTURE.md P1) -----------------------------------------

def test_the_system_prompt_does_not_hardcode_san_diego():
    """The exact bug class `agent/score.py: _preamble` was fixed for, live here too:
    the assistant is CLAUDE.md's own answer to "the user never writes a prompt", and it
    was telling every tenant's model it worked for a nonprofit in San Diego and Imperial
    Counties regardless of who actually pasted the link."""
    from app.assistant import _system

    assert "san diego" not in _system().lower()
    assert "imperial" not in _system().lower()


def test_an_orgs_own_name_and_location_reach_the_prompt():
    from app.assistant import _system

    system = _system(org_name="Casa Familiar", org_location="San Ysidro, California")
    assert "Casa Familiar" in system
    assert "San Ysidro, California" in system


def test_an_org_with_nothing_stated_gets_an_honest_prompt_not_a_guess():
    """Empty is passed through as empty — a guessed region is the bug, not a missing
    one (the same rule `_preamble`'s own docstring states)."""
    from app.assistant import _system

    system = _system(org_name="", org_location="")
    assert "You are helping the COO of a nonprofit," in system
    assert "working in" not in system
