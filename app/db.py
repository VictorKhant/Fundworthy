"""SQLite store — schema, connections, migrations. (CLAUDE.md)

One file on disk, no server, no ORM. The whole store is small enough to read in one
sitting, which matters more than elegance for something the organization has to maintain
after we leave.

Four things live here that used to live in a Google Sheet or in Python source:

  settings       the award floor, the runway, the caps, the kill switch, the API key
  programs       the organization's programs as editable cards, ticked on or off per week
  funders        the partner list, editable — no longer hardcoded in agent/sources.py
  opportunities  this month's findings, which is also the dedup index and the archive
  runs           the run log

On dedup and the monthly purge
------------------------------
`opportunities.id` is a TEXT PRIMARY KEY holding `stable_id(source_url, title)`. SQLite
backs a TEXT PRIMARY KEY with a unique index, so "have we already shown the user this?" is
an index probe, not a scan — constant time in practice regardless of how many rows the
month accumulated. That check runs in the free deterministic tier, so a repeat finding
costs $0.00 rather than a Haiku call.

The purge is deliberately blunt: at the start of every run, every row from a month
earlier than the current one is deleted. That keeps the file from growing without bound
and means a grant seen in July is allowed to resurface in August. That resurfacing is
intended, not a bug — it is the documented exception (CLAUDE.md).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/rise.db")

SCHEMA_VERSION = 7

# The org that owns everything written before tenancy existed. A single-tenant install
# (and every row in the pilot's live database) belongs to it, so adding org scoping is a
# migration rather than a data loss. It is also the org a local, sign-in-off install uses,
# which is what keeps `./start.sh` a zero-configuration experience.
DEFAULT_ORG_ID = "default"

# --- schema -------------------------------------------------------------------

# Tenancy note. Two of the id columns below are DERIVED from content, not random:
# `funders.id` is a hash of (name, url) and `opportunities.id` is stable_id(source_url,
# title). That is deliberate and load-bearing — it is what makes "have we shown this
# already?" an index probe costing $0.00. But it also means two orgs that look at the same
# funder compute the SAME id, so a bare `id TEXT PRIMARY KEY` would have the second org's
# row silently overwrite the first's. Every per-org table is therefore keyed on
# (org_id, id), and every query carries an org_id predicate.
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orgs (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- One row per person who has ever signed in. `uid` is Firebase's `sub` claim, which is
-- stable for the life of the account; `email` is what the allow-list matches on and what
-- a human recognises, so both are kept. A user belongs to exactly one org. Many users
-- may share an org — that is how two staff at the same nonprofit see the same funders —
-- but there is no UI to arrange it yet, so today every new signer-in gets their own.
CREATE TABLE IF NOT EXISTS users (
    uid        TEXT PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    org_id     TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);

-- An invitation to join an existing org. The admin generates one and shares the code
-- however they like (email, Slack, out loud); the joiner pastes it during sign-up.
--
-- Deliberately a code rather than an emailed link: sending mail needs a provider, a
-- domain reputation, and a bounce story, and CLAUDE.md rules out the app sending mail
-- on anyone's behalf. A code the admin sends through a channel they already trust does
-- the same job with none of that.
CREATE TABLE IF NOT EXISTS invites (
    code       TEXT PRIMARY KEY,
    org_id     TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    created_by TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    -- Single-use. `redeemed_by` is kept rather than deleting the row, so an admin can
    -- see who used which invite.
    redeemed_at TEXT,
    redeemed_by TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    org_id     TEXT NOT NULL DEFAULT 'default',
    key        TEXT NOT NULL,
    value      TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (org_id, key)
);

CREATE TABLE IF NOT EXISTS programs (
    org_id         TEXT NOT NULL DEFAULT 'default',
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    slug           TEXT NOT NULL,
    summary        TEXT NOT NULL DEFAULT '',
    what_it_funds  TEXT NOT NULL DEFAULT '',
    keywords       TEXT NOT NULL DEFAULT '[]',   -- json array
    funder_types   TEXT NOT NULL DEFAULT '[]',   -- json array
    search_queries TEXT NOT NULL DEFAULT '[]',   -- json array
    min_award      INTEGER,                      -- null = use the global floor
    active         INTEGER NOT NULL DEFAULT 0,   -- ticked for this week's run
    source_url     TEXT NOT NULL DEFAULT '',
    drafted_by_ai  INTEGER NOT NULL DEFAULT 0,   -- was this card AI-drafted?
    reviewed_by_human INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS funders (
    org_id      TEXT NOT NULL DEFAULT 'default',
    id          TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT,
    sector      TEXT NOT NULL DEFAULT 'other',
    funder_type TEXT NOT NULL DEFAULT 'other',
    -- An existing organization relationship. Kept as a LABEL only. It used to boost the
    -- score and sort first; the stakeholder has since said the opposite — they already get
    -- money from those funders consistently and do not want to reapply — so warmth is
    -- now a reason to consider EXCLUDING, never a reason to rank higher.
    warm        INTEGER NOT NULL DEFAULT 0,
    -- The remove list. Unticked = never fetched, never triaged, never scored. This is
    -- the whole point: excluding at the crawl stage costs nothing, where excluding
    -- after scoring would have already spent the tokens.
    active      INTEGER NOT NULL DEFAULT 1,
    exclude_reason TEXT NOT NULL DEFAULT '',  -- why they took it off the list
    -- 990 lookup, cached here rather than repeated per run: a funder's filings change
    -- once a year, so this is ~40 requests once and effectively never again.
    ein                    TEXT,
    form_990_url           TEXT,
    form_990_year          INTEGER,
    form_990_total_revenue INTEGER,
    form_990_total_expenses INTEGER,
    form_990_checked_at    TEXT,
    tier        INTEGER NOT NULL DEFAULT 1,
    confidence  INTEGER NOT NULL DEFAULT 1,   -- agent.sources.Confidence
    programs    TEXT NOT NULL DEFAULT '[]',   -- json array of program slugs
    -- Key into agent/apis.py ADAPTERS. NULL means "crawl the HTML". Stored rather
    -- than re-derived, because a source that loses its adapter silently becomes an
    -- ordinary web page and stops being read at all.
    adapter     TEXT,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (org_id, id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    org_id                 TEXT NOT NULL DEFAULT 'default',
    id                     TEXT NOT NULL,      -- stable_id(source_url, title)
    run_id                 TEXT,
    month_key              TEXT NOT NULL,      -- 'YYYY-MM' — the purge + dedup partition
    found_on               TEXT NOT NULL,      -- date first surfaced to the user
    title                  TEXT NOT NULL,
    funder                 TEXT NOT NULL,
    source_url             TEXT NOT NULL,
    award_min              INTEGER,
    award_max              INTEGER,
    award_typical          INTEGER,
    deadline               TEXT,
    deadline_type          TEXT NOT NULL DEFAULT 'unknown',
    estimated_effort_hours INTEGER,
    program_match          TEXT NOT NULL DEFAULT '[]',
    score                  INTEGER NOT NULL DEFAULT 0,
    score_rationale        TEXT NOT NULL DEFAULT '',
    funder_type            TEXT NOT NULL DEFAULT 'unknown',
    service_areas          TEXT NOT NULL DEFAULT '[]',
    geography              TEXT,
    form_990_available     INTEGER,            -- null = unknown
    confidence_pct         INTEGER,
    contact_note           TEXT,
    verified               INTEGER NOT NULL DEFAULT 0,
    needs_human_check      INTEGER NOT NULL DEFAULT 1,
    section                TEXT NOT NULL DEFAULT 'not_stated',
    -- Funder page vs public grants database. Same accuracy rules either way, but very
    -- different starting positions for a conversation, so the user gets to see which.
    source_kind            TEXT NOT NULL DEFAULT 'funder_page',
    -- The COO's own criteria (§11 Q5). Two different kinds of time, which they
    -- separated and we had conflated: days to BE READY to submit, vs days from
    -- submitting to money in the bank.
    application_lead_time_days INTEGER,
    time_to_funds_days     INTEGER,
    ein                    TEXT,
    form_990_url           TEXT,
    form_990_year          INTEGER,
    form_990_total_revenue INTEGER,
    form_990_total_expenses INTEGER,
    fetched_at             TEXT NOT NULL,
    PRIMARY KEY (org_id, id)
);

CREATE TABLE IF NOT EXISTS runs (
    org_id             TEXT NOT NULL DEFAULT 'default',
    -- Run ids are uuids, so they do not collide across orgs the way the derived ids
    -- above do; org_id here is for scoping reads, not for identity.
    id                 TEXT PRIMARY KEY,
    -- Who pressed the button. Null for a scheduled run, which nobody pressed.
    started_by         TEXT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT NOT NULL DEFAULT 'running',  -- running | done | failed | stopped
    stop_reason        TEXT,
    usd_spent          REAL NOT NULL DEFAULT 0.0,
    sources_attempted  INTEGER NOT NULL DEFAULT 0,
    sources_ok         INTEGER NOT NULL DEFAULT 0,
    sources_failed     INTEGER NOT NULL DEFAULT 0,
    candidates_parsed  INTEGER NOT NULL DEFAULT 0,
    rejected_by_filter TEXT NOT NULL DEFAULT '{}',
    opportunities_scored     INTEGER NOT NULL DEFAULT 0,
    opportunities_not_stated INTEGER NOT NULL DEFAULT 0,
    purged_rows        INTEGER NOT NULL DEFAULT 0,
    duplicates_skipped INTEGER NOT NULL DEFAULT 0,
    notes              TEXT NOT NULL DEFAULT '[]',
    -- Per-source outcome. Without this a broken funder and a genuinely quiet week
    -- look identical on the dashboard, which is the one ambiguity that costs trust.
    source_health      TEXT NOT NULL DEFAULT '[]',
    progress           TEXT NOT NULL DEFAULT '{}'
);
"""

# Indexes live apart from the table DDL because every one of them names `org_id`, and on
# an install that predates tenancy that column does not exist until `_migrate` has run.
# Creating them in the same script as the tables meant a v6 database failed to open at
# all: `CREATE TABLE IF NOT EXISTS` was a harmless no-op, and the very next CREATE INDEX
# then referenced a column the old table did not have. Tables, then migrate, then these.
INDEXES = """
CREATE INDEX        IF NOT EXISTS idx_users_org         ON users(org_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_programs_org_slug ON programs(org_id, slug);
CREATE INDEX        IF NOT EXISTS idx_programs_org      ON programs(org_id);
CREATE INDEX        IF NOT EXISTS idx_funders_org       ON funders(org_id);
CREATE INDEX        IF NOT EXISTS idx_opp_month         ON opportunities(org_id, month_key);
CREATE INDEX        IF NOT EXISTS idx_opp_run           ON opportunities(run_id);
CREATE INDEX        IF NOT EXISTS idx_runs_started      ON runs(org_id, started_at DESC);
CREATE INDEX        IF NOT EXISTS idx_invites_org       ON invites(org_id);
"""


# --- defaults -----------------------------------------------------------------

# §11 Q1 is ANSWERED: $10,000 is the smallest award worth 10 hours of team time.
# The placeholder machinery that used to guard this is gone (CLAUDE.md).
MIN_AWARD_DEFAULT = 10_000

DEFAULT_SETTINGS: dict[str, str] = {
    "min_award": str(MIN_AWARD_DEFAULT),
    "min_deadline_runway_days": "14",
    "max_opportunities": "12",
    "run_budget_usd": "1.00",
    # The org's own ceiling on what Fundworthy may spend of their Anthropic credit in a
    # calendar month, across every run. `run_budget_usd` bounds one run; this bounds the
    # bill. Enforced in app/runner.py before a run is launched.
    #
    # It is deliberately *our* number rather than a reading of their Anthropic balance:
    # Anthropic exposes no credit-balance endpoint or header (the `anthropic-ratelimit-*`
    # headers are tokens-per-minute, which refill, not dollars). So we cap what we spend
    # and show what we spent, and onboarding tells the org to also set a spend limit in
    # their own Anthropic console — the only ceiling that survives a bug in this one.
    "monthly_budget_usd": "20.00",
    "enabled": "1",
    # The taxonomy is a placeholder until the user answers FUTURE.md ("what are
    # the four sectors?"). Their answer renames labels; it does not change code.
    "sectors_active": json.dumps(
        ["warm_partner", "foundation", "government", "arts_agency"]
    ),
    "search_beyond_partners": "0",  # lights up once the discovery provider lands
    # Who this install is for. Empty by default and shown as "Your organization" until
    # someone fills it in — the UI used to hardcode the organization's name in a dozen
    # places, which is wrong for anyone else and was never a fact the code should have
    # been asserting.
    "org_name": "",
    "org_location": "",
    # When the weekly search runs, per org. It used to be "Wednesday 11pm PT" written
    # into a config dataclass that nothing read and a sentence in the UI that nothing
    # enforced — there was no scheduler at all, so the only way a search happened was
    # somebody pressing Re-run.
    #
    # A day and an hour in the org's own timezone, because "Thursday morning, before her
    # Thursday meeting" is the actual requirement and that is a local-time statement. The
    # `enabled` setting above stays the kill switch: off means nothing is scheduled.
    "schedule_day": "wednesday",
    "schedule_hour": "23",
    "schedule_timezone": "America/Los_Angeles",
}

# Seeded onto the REMOVE LIST, with the reason recorded. The organization already receives
# money from these and does not want to reapply, so searching them spends tokens producing
# rows the user skips. Each is one click from being searched again if they disagree.
#
# The last entry is not a funder but a PROGRAMME — §7's "done, no more funding". It was
# previously a hardcoded reject in filters.py that matched on funder name and therefore
# never fired once. On the remove list it matches the page title, so the programme is
# excluded and the rest of the County stays eligible, which is what §7 asked for.
REMOVE_LIST_SEED: dict[str, str] = {
    "San Diego Foundation": "Already funded by them — no need to reapply",
    "Alliance Healthcare Foundation": "Already funded by them — no need to reapply",
    "Prebys Foundation": "Already funded by them — no need to reapply",
    "City of San Diego Economic Development": "Already funded by them — no need to reapply",
    "City of San Diego Commission for Arts and Culture":
        "Already funded by them — no need to reapply",
    "California Arts Council": "Already funded by them — no need to reapply",
    "The Morales Fund": "Already funded by them — no need to reapply",
    "The Villegas Fund": "Already funded by them — no need to reapply",
    "County of San Diego Equity Impact Grant": "Done — no more funding (CLAUDE.md)",
}

SECTORS = ("warm_partner", "foundation", "government", "arts_agency",
           "intermediary", "corporate", "other")

FUNDER_TYPES = ("private_foundation", "corporate", "community", "government",
                "public_agency", "other", "unknown")


# --- connection ---------------------------------------------------------------

def db_path() -> Path:
    return Path(os.environ.get("FUNDWORTHY_DB_PATH") or DEFAULT_DB_PATH)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """A fresh connection with the pragmas we depend on.

    `check_same_thread=False` because FastAPI runs sync endpoints on a threadpool and
    the pipeline runs on a background thread. Each caller opens and closes its own
    connection, so no handle is ever shared across threads — WAL handles the
    concurrency between them.
    """
    target = Path(path) if path is not None else db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def session(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Transaction scope. Commits on success, rolls back on any exception."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | str | None = None, *, seed: bool = True) -> None:
    """Create the schema if absent, run migrations, and seed first-boot rows."""
    with session(path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(INDEXES)
        ensure_org(conn, DEFAULT_ORG_ID)
        if seed:
            seed_org(conn, DEFAULT_ORG_ID)


def seed_org(conn: sqlite3.Connection, org_id: str) -> None:
    """Give an org its starting content: **settings, and nothing else.**

    Both of the things that used to be seeded here have moved out, for different reasons.

    **Funders** are a directory an org imports from (`agent/directory.py`). Seeding them
    meant whichever org signed in first inherited 52 and the account created five minutes
    later got none — an artefact of `DEFAULT_ORG_ID` existing, not a rule anyone chose.

    **Program cards** are not seeded at all, and there is deliberately no directory to
    import them from either. A funder list is shared knowledge — who gives money, in this
    city — so one org researching it can be useful to the next. A program card is the
    opposite: it describes what *this* nonprofit does, in their words, and another org's
    cards are not merely unhelpful but actively wrong. Handing a new account seven cards
    about somebody else's arts and resilience programs made the app look configured when
    it was not, and the first thing they had to do was work out what to delete.

    A new org therefore starts with an empty dashboard and the onboarding checklist,
    whose second step is "describe what you do" — paste a link to your own website and
    the assistant drafts a card you correct. That is the intended first five minutes, and
    it only works if the page is actually empty.

    **Funders are the exception, and they come back.** They were seeded, then removed
    entirely when it turned out whoever signed in first inherited 52 and the next account
    got none. Removing them fixed the unfairness and introduced a worse problem: a new
    account opened onto an empty list, and a Re-run with no funders does nothing at all.
    Every org now gets the same starter lists, so it is even *and* the app works on the
    first click. Which lists is `agent/directory.DEFAULT_ON_SIGNUP`, and choosing your own
    city is the Discover funders page.

    Settings still reconcile on every boot rather than once: `seed_settings` is INSERT ...
    ON CONFLICT DO NOTHING per key, so a genuinely new setting appears for an existing org
    without touching a value anyone has chosen.
    """
    seed_settings(conn, org_id)

    # Once. The marker is what stops a restart or a pipeline run resurrecting a funder
    # the org deliberately removed — the bug this whole seeding path had before.
    marker = f"seeded_at:{org_id}"
    if conn.execute("SELECT 1 FROM meta WHERE key=?", (marker,)).fetchone():
        return

    from agent.directory import DEFAULT_ON_SIGNUP

    for key in DEFAULT_ON_SIGNUP:
        import_starter_list(conn, key, org_id)
    conn.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (marker, now_iso()))


def _migrate(conn: sqlite3.Connection) -> None:
    """Forward-only migrations keyed off meta.schema_version.

    There is exactly one version today. The hook exists so that adding a column after
    the organization is already running does not mean asking someone to delete their database.
    """
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    current = int(row["value"]) if row else 0

    if current < 1:
        # v1 is the base schema, already applied by executescript above.
        current = 1

    if current < 2:
        # v2 lands both halves of the merge with the indexed-source work:
        #   funders.adapter    so the CA Grants Portal and Grants.gov survive the
        #                      round trip and keep being read as APIs, not web pages
        #   runs.source_health so "a funder broke" and "a quiet week" stay distinct
        # CREATE TABLE above has both on a fresh install; these are for a v1 database.
        funder_cols = {r["name"] for r in conn.execute("PRAGMA table_info(funders)")}
        if "adapter" not in funder_cols:
            conn.execute("ALTER TABLE funders ADD COLUMN adapter TEXT")
        run_cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
        if "source_health" not in run_cols:
            conn.execute(
                "ALTER TABLE runs ADD COLUMN source_health TEXT NOT NULL DEFAULT '[]'")
        current = 2

    if current < 3:
        # v3 adds opportunities.source_kind. Without it the sink silently discarded
        # the provenance tag, so every record read back as a funder page regardless of
        # where it actually came from.
        opp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
        if "source_kind" not in opp_cols:
            conn.execute("ALTER TABLE opportunities ADD COLUMN source_kind "
                         "TEXT NOT NULL DEFAULT 'funder_page'")
        current = 3

    if current < 4:
        # v4 adds funders.exclude_reason — the remove list records WHY, because
        # "we already get money from them" and "they stopped funding us" both mean
        # don't search, and a year from now nobody will remember which was which.
        funder_cols = {r["name"] for r in conn.execute("PRAGMA table_info(funders)")}
        if "exclude_reason" not in funder_cols:
            conn.execute("ALTER TABLE funders ADD COLUMN exclude_reason "
                         "TEXT NOT NULL DEFAULT ''")
        current = 4

    if current < 5:
        # v5 lands the COO's answer to the forced-rank (§11 Q5): the two time criteria
        # on opportunities, and cached 990 facts on both tables.
        for table, cols in (
            ("funders", [
                ("ein", "TEXT"), ("form_990_url", "TEXT"),
                ("form_990_year", "INTEGER"), ("form_990_total_revenue", "INTEGER"),
                ("form_990_total_expenses", "INTEGER"), ("form_990_checked_at", "TEXT"),
            ]),
            ("opportunities", [
                ("application_lead_time_days", "INTEGER"), ("time_to_funds_days", "INTEGER"),
                ("ein", "TEXT"), ("form_990_url", "TEXT"), ("form_990_year", "INTEGER"),
                ("form_990_total_revenue", "INTEGER"), ("form_990_total_expenses", "INTEGER"),
            ]),
        ):
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, kind in cols:
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
        current = 5

    if current < 6:
        # v6 puts the eight former partners and the County Equity Impact Grant on the
        # remove list. Only touches rows the user has not already made a decision about —
        # an empty exclude_reason means nobody has ticked or unticked it — so a database
        # where they have already chosen is left exactly as they left it.
        for name, reason in REMOVE_LIST_SEED.items():
            conn.execute(
                "UPDATE funders SET active=0, exclude_reason=? "
                "WHERE lower(name)=lower(?) AND exclude_reason=''",
                (reason, name),
            )
        # NB: no insert here. This runs before seed_funders, so inserting into an empty
        # table would duplicate every name once seed_funders adds its url-keyed rows.
        # init_db calls seed_remove_list_only after seeding, for fresh and existing both.
        current = 6

    if current < 7:
        _migrate_to_org_scoped(conn)
        current = 7

    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(current),),
    )


def _migrate_to_org_scoped(conn: sqlite3.Connection) -> None:
    """v7 — give every row an owner.

    Everything written before this migration belongs to one install and therefore to one
    org, so it all moves to `DEFAULT_ORG_ID` and nothing is lost. The pilot org keeps its
    funders, its program cards, its findings, and its saved API key exactly as they were.

    Four of the five tables need a genuine rebuild rather than an ALTER, because their
    PRIMARY KEY changes and SQLite cannot alter one in place. The pattern is the standard
    rename-create-copy-drop. `runs` only gains columns, so it takes plain ALTERs.

    Not wrapped in a savepoint: `executescript` commits any open transaction before it
    runs, so a crash midway leaves the `*__pre_org` tables on disk. That is recoverable by
    hand and visible, which is the right failure mode for a migration that moves a
    nonprofit's only copy of its data.
    """
    stamp = now_iso()
    conn.execute(
        "INSERT INTO orgs(id, name, created_at) VALUES(?,?,?) "
        "ON CONFLICT(id) DO NOTHING",
        (DEFAULT_ORG_ID, "", stamp),
    )

    rebuilt = ("settings", "programs", "funders", "opportunities")
    carried: dict[str, list[str]] = {}

    for table in rebuilt:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if not cols or "org_id" in cols:
            continue                      # fresh install, or already migrated
        carried[table] = cols
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}__pre_org")

    # A renamed table keeps its indexes, under their original names — so unless these go
    # first, the CREATE INDEX IF NOT EXISTS in `INDEXES` is a silent no-op and the rebuilt
    # tables end up unindexed. That would not fail any test; it would just make every
    # dashboard load slower every month, which is exactly the kind of thing nobody notices.
    for index in ("idx_opp_month", "idx_opp_run", "idx_runs_started"):
        conn.execute(f"DROP INDEX IF EXISTS {index}")

    if carried:
        conn.executescript(SCHEMA)        # recreates the four, now org-scoped

    for table, cols in carried.items():
        names = ", ".join(cols)
        conn.execute(
            f"INSERT INTO {table}(org_id, {names}) SELECT ?, {names} FROM {table}__pre_org",
            (DEFAULT_ORG_ID,),
        )
        conn.execute(f"DROP TABLE {table}__pre_org")

    run_cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    if "org_id" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN org_id TEXT NOT NULL DEFAULT 'default'")
    if "started_by" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN started_by TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(org_id, started_at DESC)")

    if carried:
        # This install has been seeded — by definition, since it has pre-tenancy rows.
        # Without this marker the first boot after migrating would run the seeders again
        # and hand the pilot org back every funder and program card they had deleted.
        conn.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                     "ON CONFLICT(key) DO NOTHING",
                     (f"seeded_at:{DEFAULT_ORG_ID}", now_iso()))

    log.info("migrated %d table(s) to org-scoped storage; existing rows belong to %r",
             len(carried), DEFAULT_ORG_ID)


# --- orgs and users -----------------------------------------------------------

def ensure_org(conn: sqlite3.Connection, org_id: str, name: str = "") -> None:
    conn.execute(
        "INSERT INTO orgs(id, name, created_at) VALUES(?,?,?) "
        "ON CONFLICT(id) DO NOTHING",
        (org_id, name, now_iso()),
    )


def _claims_default_org(conn: sqlite3.Connection, email: str) -> bool:
    """May this address adopt the pre-tenancy org?

    Two ways to say yes, and neither is "you got here first":

      1. `FUNDWORTHY_PILOT_EMAILS` names them. This is the deployed answer — the operator
         writes down who the existing data belongs to.
      2. Nobody has ever signed in AND the org is empty. A genuinely fresh install has
         nothing to steal, so its first user may as well have the default org rather than
         accumulating an orphan beside it.

    An install with existing data and no `FUNDWORTHY_PILOT_EMAILS` therefore hands that
    data to nobody. That is deliberate: the org is still there, and one env var plus a
    restart reunites its owner with it. There is no equivalent undo for having given a
    stranger someone else's API key.
    """
    claimants = {e.strip().casefold()
                 for e in os.environ.get("FUNDWORTHY_PILOT_EMAILS", "").split(",")
                 if e.strip()}
    if claimants:
        return email.strip().casefold() in claimants

    nobody_yet = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
    if not nobody_yet:
        return False

    # What counts as "somebody's data" is narrower than it looks. Shipped seed content —
    # the 44 researched funders and the program cards — is not somebody's work; it is a
    # starting point every fresh install gets. Counting it made a brand-new deployment
    # look occupied, so its first user was handed a new empty org while the seeded
    # funders sat orphaned beside it, and the operator had to set an env var to undo
    # something that should never have happened.
    #
    # Accumulated findings and a saved API key are different: those are the pilot's own,
    # and handing them to a stranger is the thing this guard exists to prevent.
    has_data = conn.execute(
        "SELECT (SELECT COUNT(*) FROM opportunities WHERE org_id=?) + "
        "       (SELECT COUNT(*) FROM settings WHERE org_id=? AND key=? "
        "        AND value IS NOT NULL) AS n",
        (DEFAULT_ORG_ID, DEFAULT_ORG_ID, "anthropic_api_key"),
    ).fetchone()["n"] > 0

    if has_data:
        log.warning(
            "%s is the first sign-in, but org %r already holds data and no "
            "FUNDWORTHY_PILOT_EMAILS is set — giving them a new org instead. Set that "
            "variable to whoever the existing data belongs to.", email, DEFAULT_ORG_ID)
        return False
    return True


def org_for_user(conn: sqlite3.Connection, uid: str, email: str) -> str:
    """The org this person belongs to, creating one on their first sign-in.

    This is the function that decides whether two people share data, so it is worth being
    explicit about today's policy: **every new signer-in gets their own empty org.** Two
    colleagues at the same nonprofit currently land in separate orgs and cannot see each
    other's work. That is the safe direction to be wrong in — the alternative default,
    dropping strangers into a shared org, is the bug this whole migration exists to fix —
    but it is not the end state. Inviting a colleague into an existing org is the next
    piece of work (FUTURE.md).

    **`DEFAULT_ORG_ID` is claimed by name, not by arriving first.** It holds everything
    written before tenancy existed — the pilot's funders, their findings, and their
    encrypted API key — so whoever lands in it can spend that key. This used to be
    "whoever signs in first", which was safe only because an allow-list meant the first
    signer was someone we trusted. With open sign-up that rule hands the pilot org's data
    and their Anthropic credit to the first stranger who finds the URL. So it is now an
    explicit list of addresses in `FUNDWORTHY_PILOT_EMAILS`, and if that is unset nobody
    adopts it — a stranded org is recoverable, a handed-over one is not.
    """
    row = conn.execute("SELECT org_id FROM users WHERE uid=?", (uid,)).fetchone()
    if row:
        conn.execute("UPDATE users SET last_seen_at=?, email=? WHERE uid=?",
                     (now_iso(), email, uid))
        return row["org_id"]

    # Same person, new Firebase uid (they deleted and remade the Google account, or the
    # project was rebuilt). Match on the address so they keep their org rather than
    # silently starting again with an empty dashboard.
    row = conn.execute("SELECT uid, org_id FROM users WHERE email=?", (email,)).fetchone()
    if row:
        conn.execute("UPDATE users SET uid=?, last_seen_at=? WHERE email=?",
                     (uid, now_iso(), email))
        return row["org_id"]

    org_id = DEFAULT_ORG_ID if _claims_default_org(conn, email) \
        else f"org_{uuid.uuid4().hex[:16]}"
    ensure_org(conn, org_id)
    conn.execute(
        "INSERT INTO users(uid, email, org_id, created_at, last_seen_at) VALUES(?,?,?,?,?)",
        (uid, email, org_id, now_iso(), now_iso()),
    )
    if org_id != DEFAULT_ORG_ID:
        # The same provisioning the default org gets, so "what do I start with" has one
        # answer rather than depending on which door you came through. Settings, and the
        # starter funder lists — **not** program cards, which describe what one nonprofit
        # does and are wrong for anybody else.
        seed_org(conn, org_id)
    log.info("first sign-in for %s — assigned to org %s", email, org_id)
    return org_id


# --- invitations --------------------------------------------------------------

INVITE_TTL_DAYS = 14

# Unambiguous alphabet: no O/0, no I/1/L. The code gets read aloud, written on paper,
# and retyped by someone who does not think of themselves as technical.
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def create_invite(conn: sqlite3.Connection, org_id: str,
                  created_by: str | None = None) -> dict:
    """A single-use code that lets one more person join `org_id`."""
    import secrets as _secrets

    raw = "".join(_secrets.choice(_INVITE_ALPHABET) for _ in range(12))
    code = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=INVITE_TTL_DAYS)
    conn.execute(
        "INSERT INTO invites(code, org_id, created_by, created_at, expires_at) "
        "VALUES(?,?,?,?,?)",
        (code, org_id, created_by, now.isoformat(), expires.isoformat()),
    )
    return {"code": code, "org_id": org_id, "expires_at": expires.isoformat()}


def list_invites(conn: sqlite3.Connection, org_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT code, created_by, created_at, expires_at, redeemed_at, redeemed_by "
        "FROM invites WHERE org_id=? ORDER BY created_at DESC", (org_id,))]


def revoke_invite(conn: sqlite3.Connection, code: str, org_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM invites WHERE code=? AND org_id=? AND redeemed_at IS NULL",
        (code.strip().upper(), org_id))
    return cur.rowcount > 0


class InviteError(ValueError):
    """The code cannot be redeemed, with a reason safe to show the person holding it."""


def redeem_invite(conn: sqlite3.Connection, code: str, uid: str, email: str) -> str:
    """Move (or place) this person into the org the code belongs to. Returns the org id.

    Redeeming is idempotent per person but single-use per code: the second person to try
    the same code is told to ask for their own. The error messages deliberately do not
    distinguish "no such code" from "already used" beyond what the holder needs to act —
    there is nothing to enumerate here, but there is also no reason to be chatty.
    """
    code = code.strip().upper()
    row = conn.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()
    if row is None:
        raise InviteError("That invitation code is not valid. Check it and try again.")
    if row["redeemed_at"]:
        raise InviteError(
            "That invitation has already been used. Ask for a new one.")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        raise InviteError("That invitation has expired. Ask for a new one.")

    org_id = row["org_id"]
    now = now_iso()
    conn.execute("UPDATE invites SET redeemed_at=?, redeemed_by=? WHERE code=?",
                 (now, email, code))

    existing = conn.execute("SELECT uid, org_id FROM users WHERE uid=? OR email=?",
                            (uid, email)).fetchone()
    if existing:
        conn.execute("UPDATE users SET uid=?, org_id=?, last_seen_at=? WHERE uid=?",
                     (uid, org_id, now, existing["uid"]))
    else:
        conn.execute(
            "INSERT INTO users(uid, email, org_id, created_at, last_seen_at) "
            "VALUES(?,?,?,?,?)", (uid, email, org_id, now, now))
    log.info("%s joined org %s by invitation", email, org_id)
    return org_id


def org_members(conn: sqlite3.Connection, org_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT email, created_at, last_seen_at FROM users WHERE org_id=? "
        "ORDER BY created_at", (org_id,))]


# --- helpers ------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def month_key(when: date | datetime | None = None) -> str:
    """'YYYY-MM'. The dedup and purge partition."""
    when = when or datetime.now(timezone.utc)
    return f"{when.year:04d}-{when.month:02d}"


def loads(value: Any, fallback: Any) -> Any:
    """json.loads that never raises — a corrupt cell degrades, it does not crash a run."""
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        log.warning("could not parse stored JSON %r — using %r", value, fallback)
        return fallback


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


# --- seeds --------------------------------------------------------------------

def seed_settings(conn: sqlite3.Connection, org_id: str = DEFAULT_ORG_ID) -> None:
    """Insert defaults for any setting not already present. Never overwrites."""
    stamp = now_iso()
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(org_id, key, value, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(org_id, key) DO NOTHING",
            (org_id, key, value, stamp),
        )


# The pilot org's programs, with URLs confirmed by fetching its own program pages.
#
# Only the three the user named as priorities ship with content, and that content comes
# from CLAUDE.md — i.e. from the intake conversation, not from us. The other four
# ship as name + real URL + empty card ON PURPOSE: filling them in is exactly what the
# "build this card from a link" assistant is for, and inventing a description of a real
# organisation's programme would be the same failure mode §6 forbids for award amounts.
SEED_PROGRAMS: list[dict] = [
    {
        "slug": "RULFP",
        "name": "RISE Urban Leadership Fellows Program",
        "source_url": "https://www.risesandiego.org/programs/rulfp",
        "active": 1,
        "summary": "Leadership pipeline for resident-led civic engagement in San Diego "
                   "and Imperial Counties.",
        "what_it_funds": "Cohort fellowship delivery, BIPOC leadership development, "
                         "DEIA capacity building.",
        "keywords": ["leadership pipeline", "adaptive leadership",
                     "resident-led civic engagement", "BIPOC leadership development",
                     "cohort fellowship", "DEIA capacity building"],
        "funder_types": ["private_foundation", "community"],
        "search_queries": [
            "BIPOC leadership development grant San Diego",
            "civic engagement fellowship funding California",
            "nonprofit leadership pipeline grant",
        ],
    },
    {
        "slug": "RESILIENCE",
        "name": "RISE Resilience & Renewal",
        "source_url": "https://www.risesandiego.org/programs/resilience",
        "active": 1,
        "summary": "Whole-body leadership and burnout recovery for nonprofit leaders. "
                   "Born out of Alliance Healthcare Foundation's i2 Challenge.",
        "what_it_funds": "Somatic practice, wellness programming, workforce retention.",
        "keywords": ["nonprofit leader burnout", "whole-body leadership",
                     "somatic practice", "polyvagal theory", "wellness",
                     "workforce retention", "health tech"],
        "funder_types": ["private_foundation", "government"],
        "search_queries": [
            "nonprofit leader burnout grant",
            "behavioral health workforce retention funding California",
            "health equity innovation grant San Diego",
        ],
    },
    {
        "slug": "ARTS",
        "name": "RISE Arts",
        "source_url": "https://www.risesandiego.org/programs/risearts",
        "active": 1,
        "summary": "Arts and social justice with artists from historically "
                   "marginalized communities.",
        "what_it_funds": "Creative placemaking, cultural equity, arts capacity building.",
        "keywords": ["arts and social justice", "historically marginalized artists",
                     "creative placemaking", "cultural equity",
                     "arts capacity building"],
        "funder_types": ["public_agency", "private_foundation"],
        "search_queries": [
            "arts and social justice grant California",
            "cultural equity funding San Diego",
            "creative placemaking grant",
        ],
    },
    # --- named by the organization, not yet described. The assistant fills these in. ---
    {
        "slug": "ILIA",
        "name": "Inclusive Leadership in Action (ILIA) Awards",
        "source_url": "https://www.risesandiego.org/programs/ilia",
        "active": 0,
    },
    {
        "slug": "RISE_NOW",
        "name": "RISE Now",
        "source_url": "https://www.risesandiego.org/programs/risenow",
        "active": 0,
    },
    {
        "slug": "ON_THE_RISE",
        "name": "On the RISE",
        "source_url": "https://www.risesandiego.org/programs/ontherise",
        "active": 0,
    },
    {
        "slug": "NP_TRAININGS",
        "name": "Nonprofit Partnerships Training",
        "source_url": "https://www.risesandiego.org/programs/nptrainings",
        "active": 0,
    },
]


def seed_programs(conn: sqlite3.Connection, org_id: str = DEFAULT_ORG_ID) -> None:
    """First boot only. Never overwrites a card the user has edited."""
    stamp = now_iso()
    for p in SEED_PROGRAMS:
        conn.execute(
            """INSERT INTO programs(
                   org_id, id, name, slug, summary, what_it_funds, keywords, funder_types,
                   search_queries, min_award, active, source_url, drafted_by_ai,
                   reviewed_by_human, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?)
               ON CONFLICT(org_id, slug) DO NOTHING""",
            (
                org_id, f"{org_id}:{p['slug'].lower()}", p["name"], p["slug"],
                p.get("summary", ""), p.get("what_it_funds", ""),
                dumps(p.get("keywords", [])), dumps(p.get("funder_types", [])),
                dumps(p.get("search_queries", [])), p.get("min_award"),
                int(p.get("active", 0)), p.get("source_url", ""),
                stamp, stamp,
            ),
        )


def import_starter_list(conn: sqlite3.Connection, key: str, org_id: str) -> int:
    """Copy one of the shipped funder lists into this org. Returns how many are new.

    Idempotent by (org_id, id): importing twice adds nothing and, crucially, does not
    resurrect a funder the org deliberately removed — `ON CONFLICT DO NOTHING` leaves an
    existing row exactly as the user left it, un-ticked reasons and all.
    """
    from agent.directory import get as get_list
    from agent.sources import sector_for

    lst = get_list(key)
    if lst is None:
        raise ValueError(f"no starter list called {key!r}")

    stamp = now_iso()
    added = 0
    for s in lst.sources:
        cur = conn.execute(
            """INSERT INTO funders(
                   org_id, id, name, url, sector, funder_type, warm, active,
                   exclude_reason, tier, confidence, programs, adapter, notes,
                   created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,1,'',?,?,?,?,?,?,?)
               ON CONFLICT(org_id, id) DO NOTHING""",
            (org_id, _funder_id(s.funder, s.url), s.funder, s.url, sector_for(s),
             _funder_type_for(s), int(s.warm), int(s.tier), int(s.confidence),
             dumps([p.value for p in s.programs]), s.adapter, s.notes, stamp, stamp),
        )
        added += cur.rowcount or 0
    log.info("org %s imported %d funder(s) from the %r list", org_id, added, key)
    return added


def seed_funders(conn: sqlite3.Connection, org_id: str = DEFAULT_ORG_ID) -> None:
    """Seed the partner list from agent/sources.py on first boot.

    The registry stays in agent/sources.py as the shipped starting point — deleting it
    would collide with the teammate's discovery branch and would lose the URL-confidence
    research already done there. From here on the DB is authoritative: the user adds,
    edits, and deactivates partners in the dashboard, and a funder who stops funding
    the organization gets deactivated rather than deleted, so the relationship history survives.
    """
    from agent.sources import ALL_SOURCES, sector_for

    stamp = now_iso()
    removed = {k.casefold(): v for k, v in REMOVE_LIST_SEED.items()}
    for s in ALL_SOURCES:
        reason = removed.get(s.funder.strip().casefold(), "")
        conn.execute(
            """INSERT INTO funders(
                   org_id, id, name, url, sector, funder_type, warm, active,
                   exclude_reason, tier, confidence, programs, adapter, notes,
                   created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(org_id, id) DO UPDATE SET
                   -- Only ever backfill the adapter. Everything else on an existing
                   -- row is the user's, and a re-seed must not overwrite their edits.
                   adapter=COALESCE(funders.adapter, excluded.adapter)""",
            (
                org_id, _funder_id(s.funder, s.url), s.funder, s.url, sector_for(s),
                _funder_type_for(s), int(s.warm), 0 if reason else 1, reason,
                int(s.tier), int(s.confidence),
                dumps([p.value for p in s.programs]), s.adapter, s.notes, stamp, stamp,
            ),
        )


def seed_remove_list_only(conn: sqlite3.Connection, org_id: str = DEFAULT_ORG_ID) -> None:
    """Remove-list entries that are not sources in their own right.

    "County of San Diego Equity Impact Grant" is a PROGRAMME, not a funder — §7 is
    explicit that the rest of the County stays eligible. It has no registry row to mark,
    so it gets a row here whose only job is to be on the remove list and be matched
    against page titles.

    This is also what makes the remove list the user's single lever: they can exclude a
    whole funder or one named programme from the same place, and see both.
    """
    stamp = now_iso()
    existing = {r["name"].casefold() for r in
                conn.execute("SELECT name FROM funders WHERE org_id=?", (org_id,))}
    for name, reason in REMOVE_LIST_SEED.items():
        if name.casefold() in existing:
            continue
        conn.execute(
            """INSERT INTO funders(
                   org_id, id, name, url, sector, funder_type, warm, active,
                   exclude_reason, tier, confidence, programs, notes,
                   created_at, updated_at)
               VALUES(?,?,?,NULL,'other','other',0,0,?,1,0,'[]',?,?,?)
               ON CONFLICT(org_id, id) DO NOTHING""",
            (org_id, _funder_id(name), name, reason,
             "On the remove list only — a named programme rather than a funder we crawl.",
             stamp, stamp),
        )


def _funder_id(name: str, url: str | None = None) -> str:
    """Seed identity for a registry entry: name AND url.

    Name alone is not unique. Grants.gov and SAM.gov are both `funder="U.S. Federal
    Government"` in sources.py, so hashing the name collapsed them into one row and
    SAM.gov vanished from the registry with no error anywhere — the seed just wrote
    over itself. Including the URL keeps distinct entries distinct.

    (`create_funder` still keys on name alone, deliberately: when the user types a funder
    that is already on their list, updating that row is what they mean, not adding a
    second one with the same name.)
    """
    import hashlib

    payload = f"{name.strip().casefold()}|{(url or '').strip().rstrip('/')}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _funder_type_for(source) -> str:
    name = source.funder.casefold()
    if "city of" in name or "county of" in name or "government" in name:
        return "government"
    if "california arts council" in name:
        return "public_agency"
    if "foundation" in name or "fund" in name:
        return "private_foundation"
    return "other"
