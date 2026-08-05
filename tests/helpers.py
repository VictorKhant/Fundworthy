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
