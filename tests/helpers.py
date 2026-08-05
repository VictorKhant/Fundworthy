"""Shared setup that is not a fixture.

Funders are no longer seeded into any org automatically — they are a directory an org
imports from (`agent/directory.py`), because seeding them meant whichever org signed in
first got 52 funders and the account created five minutes later got none. Tests that
exercise the funder list, the remove list, or the source registry still need them, so
they ask for them here.
"""

from __future__ import annotations


def seed_starter_funders(path=None) -> None:
    """Give a test database the shipped funder list, as `init_db` used to."""
    from app.db import DEFAULT_ORG_ID, seed_funders, seed_remove_list_only, session

    with session(path) as conn:
        seed_funders(conn, DEFAULT_ORG_ID)
        seed_remove_list_only(conn, DEFAULT_ORG_ID)


def seed_starter_programs(path=None) -> None:
    """Give a test database the pilot's program cards.

    No org gets these any more. A program card describes what one nonprofit does, in
    their words, so another org's cards are not merely unhelpful but wrong — a new
    account starts with an empty dashboard and drafts its own. The pilot's seven cards
    remain in `app/db.py: SEED_PROGRAMS` because the calibration and program-wiring tests
    need a realistic set to exercise, and inventing a second fake one would mean two
    sets to keep honest.
    """
    from app.db import DEFAULT_ORG_ID, seed_programs, session

    with session(path) as conn:
        seed_programs(conn, DEFAULT_ORG_ID)
