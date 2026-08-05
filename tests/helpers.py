"""Shared setup that is not a fixture.

Funders are no longer seeded into any org automatically — they are a directory an org
imports from (`agent/directory.py`), because seeding them meant whichever org signed in
first got 52 funders and the account created five minutes later got none. Tests that
exercise the funder list, the remove list, or the source registry still need them, so
they ask for them here.
"""

from __future__ import annotations


def seed_starter_funders(path=None) -> None:
    """Give a test database the shipped funder list **with the pilot's remove list on it**.

    `init_db` gives every org the starter funders, all of them active — which is right,
    because a funder being active is the default and nobody has told us otherwise.

    The eight names in `REMOVE_LIST_SEED` are different: they mean "the pilot org already
    receives money from these and does not want to reapply". That is one nonprofit's
    relationship, not a fact about the funder, so a Chicago org signing up must not
    inherit it. It is applied here rather than on import for exactly that reason, and the
    tests that assert on it are asserting about the pilot's configuration.
    """
    from app.db import (DEFAULT_ORG_ID, REMOVE_LIST_SEED, seed_funders,
                        seed_remove_list_only, session)

    with session(path) as conn:
        seed_funders(conn, DEFAULT_ORG_ID)
        seed_remove_list_only(conn, DEFAULT_ORG_ID)
        for name, reason in REMOVE_LIST_SEED.items():
            conn.execute(
                "UPDATE funders SET active=0, exclude_reason=? "
                "WHERE lower(name)=lower(?) AND org_id=? AND exclude_reason=''",
                (reason, name, DEFAULT_ORG_ID))


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
