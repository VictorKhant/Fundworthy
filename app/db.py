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

SCHEMA_VERSION = 15

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
    -- Who administers this org: the uid of whoever created it, or of whoever it was
    -- handed to. Nullable, because a local install has no users at all and an org whose
    -- last member left keeps existing (see `strand_org`) with nobody to own it.
    --
    -- A uid rather than an email: emails are the thing a person changes.
    owner_uid  TEXT,
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

-- Somebody saying "this shared funder is wrong, or should not be here".
--
-- One report hides it from the pool immediately, before anyone reviews it. That is the
-- deliberate direction to fail in: the cost of hiding a good funder for a few days is
-- that one nonprofit misses one grant page they could have added by hand anyway, and the
-- cost of leaving a bad one up is somebody spending an afternoon writing to nobody. An
-- install admin then takes it down for good or dismisses the report and restores it.
CREATE TABLE IF NOT EXISTS funder_reports (
    id          TEXT PRIMARY KEY,
    -- The (org_id, id) of the funder row that was shared. Kept as two plain columns
    -- rather than a foreign key: the contributing org may be deleted while the report is
    -- still open, and a report that vanishes with its subject is not a moderation queue.
    funder_org  TEXT NOT NULL,
    funder_id   TEXT NOT NULL,
    reported_by TEXT NOT NULL,          -- the org that objected, never shown to anyone
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    -- 'open' until an admin acts, then 'upheld' (gone for good) or 'dismissed' (restored)
    status      TEXT NOT NULL DEFAULT 'open',
    resolved_at TEXT,
    resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_open
    ON funder_reports(status, funder_org, funder_id);

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
    -- How this funder got onto the list: 'starter' if it came from a shipped researched
    -- list, 'user' if somebody typed it in. Nothing recorded this before, and the two
    -- paths were indistinguishable afterwards — which matters now that hand-added ones
    -- are the only ones worth keeping when an org closes, and the only ones ever offered
    -- to another nonprofit. A copy of a list we ship is not a contribution.
    added_by    TEXT NOT NULL DEFAULT 'user',
    -- Evidence, not a verdict. Whether the page was reachable and looked like a grants
    -- page the last time we looked, and when. Deliberately never rendered as "verified":
    -- we can say a page loaded and mentions award amounts; we cannot say a funder is
    -- worth applying to, and a badge implying otherwise is the accuracy shortcut §8
    -- forbids. NULL means nobody has checked yet, which is not the same as failing.
    check_ok    INTEGER,
    check_note  TEXT NOT NULL DEFAULT '',
    checked_at  TEXT,
    -- Blocked, which is a third thing and not a stronger `active=0`.
    --
    --   active=0  paused. Stays on the list, greyed, not fetched. One click back.
    --   blocked   never fetched, AND never offered again — suppressed in the starter
    --             lists and in the shared directory, which `active` does not touch.
    --   deleted   the row is gone.
    --
    -- Pausing and blocking used to be the same flag, so an org that blocked a funder
    -- got it re-offered by every researched list it imported afterwards.
    blocked     INTEGER NOT NULL DEFAULT 0,
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
    -- The three parts the score is composed from, stored so a total can be taken apart.
    --
    -- The weights (40 fit / 35 award / 25 timing) used to live only as English inside
    -- the prompt: the model returned one holistic integer and nothing here could say
    -- which component produced it. "Why is this 38?" was unanswerable from the data, so
    -- a rubric that was structurally unearnable looked exactly like a weak grant.
    --
    -- **NULL means "not scorable", which is not the same as zero.** A funder that never
    -- states an award amount cannot earn or lose the 35 award points; scoring that 0/35
    -- charged the nonprofit for the funder's website being terse, and it was the single
    -- biggest reason nothing ever cleared 42/100. A null leaves that component out of
    -- the denominator instead — see `agent/score.py: compose_score`.
    fit_score              INTEGER,   -- 0-40, always present
    award_score            INTEGER,   -- 0-35, NULL when the page states no amount
    timing_score           INTEGER,   -- 0-25, NULL when there is no deadline to judge
    score_rationale        TEXT NOT NULL DEFAULT '',
    funder_type            TEXT NOT NULL DEFAULT 'unknown',
    service_areas          TEXT NOT NULL DEFAULT '[]',
    geography              TEXT,
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
    -- Per-candidate rejects: which pages each tier set aside and why. `rejected_by_filter`
    -- above counts reasons, which answers "how many" and never "which ones" — the only
    -- question somebody asks about their own funder list. Capped at models.MAX_REJECTS
    -- rows, so the counts stay complete when the list does not.
    rejects            TEXT NOT NULL DEFAULT '[]',
    -- How many candidates reached tiers 2 and 3, and what each tier cost. Derived from
    -- Budget.by_model at the end of the run rather than recomputed here, because the
    -- price table lives with the models.
    triaged            INTEGER NOT NULL DEFAULT 0,
    scored             INTEGER NOT NULL DEFAULT 0,
    usd_by_stage       TEXT NOT NULL DEFAULT '{}',
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
    # Which model runs each paid tier, as `provider:model`. Empty means "whatever
    # agent/score.py recommends", so the default follows the code rather than being
    # frozen into every org's settings row the day they signed up.
    "triage_model": "",
    "scoring_model": "",
    # Who this install is for. Empty by default and shown as "Your organization" until
    # someone fills it in — the UI used to hardcode the organization's name in a dozen
    # places, which is wrong for anyone else and was never a fact the code should have
    # been asserting.
    "org_name": "",
    "org_location": "",
    # How many collective team-hours this org can spend on one application.
    #
    # This was a constant in the scoring prompt — "a hard cap of 10 collective
    # team-hours" — which is the pilot COO's answer to a question no other org was ever
    # asked. It decides 25 of the 100 points, so every org inherited one nonprofit's
    # staffing as their own feasibility bar.
    "max_effort_hours": "10",
    # Has anybody here been walked through setting this up. **A fact that is recorded,
    # not one that is re-derived**, and that distinction is the whole point.
    #
    # Whether to show the walkthrough used to be computed live from "do you have a key,
    # a ticked program and a funder". That is a fine way to *open* the guide on the right
    # step and a terrible way to decide whether somebody is new: an established org that
    # unticked its last programme for an afternoon was thrown back to step one of
    # onboarding, on the account they had been using for months, as though it had
    # forgotten them. Setup being incomplete and the person being new are different
    # questions and only one of them can be answered by looking at the data.
    #
    # Set when they finish the walkthrough. Schema v9 backfills every org that already
    # existed to `1`, because they are self-evidently not new.
    "onboarding_done": "0",
    # Offer the funders this org typed in by hand to other nonprofits, on Discover.
    #
    # **Opt in, off by default.** A funder list is not private — a name, a grants page and
    # a sector — so sharing leaks nothing. But "not private" is not the same as "yours to
    # publish on their behalf", and an org that has never been asked has not agreed to
    # anything. Only `added_by='user'` rows are ever eligible: the shipped researched
    # lists are already on offer to everybody, so re-sharing a copy contributes nothing.
    "share_funders": "0",
    # When the weekly search runs, per org. It used to be "Wednesday 11pm PT" written
    # into a config dataclass that nothing read and a sentence in the UI that nothing
    # enforced — there was no scheduler at all, so the only way a search happened was
    # somebody pressing Re-run.
    #
    # A day and an hour in the org's own timezone, because "Thursday morning, before her
    # Thursday meeting" is the actual requirement and that is a local-time statement.
    #
    # **Off by default, and the day below is a starting point rather than a decision.**
    # `enabled` used to be the only switch, which made it two things at once: the §8 kill
    # switch *and* whether the weekly search happens. That conflation had a visible cost —
    # turning off automation greyed out "Search again now", so an org that just wanted to
    # run searches by hand could not run one at all.
    #
    # They are separate now. `enabled` stays the kill switch, default on, and gates
    # everything. `schedule_enabled` is the weekly automation alone, default **off**,
    # because an unattended job that spends an org's own API credit on a schedule they
    # never chose is not a sensible thing to opt somebody into. Wednesday 11pm was the
    # pilot's answer to a question no new org has been asked; onboarding asks it, and
    # skipping is a real answer.
    "schedule_enabled": "0",
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

    Neither of the two things a new account might expect to be handed is handed to it,
    and the reasons are different.

    **Program cards** describe what *this* nonprofit does, in their words, so another
    org's cards are not merely unhelpful but actively wrong. Seven cards about somebody
    else's arts and resilience programs made a new account look configured when it was
    not, and the first thing they had to do was work out what to delete. They write their
    own, with the assistant drafting from a link.

    **Funders** are a directory to import from (`agent/directory.py`), and this has now
    been decided three times, so the history is worth keeping:

      1. Seeded into whichever org signed in first. That org got 52 funders and the
         account created five minutes later got none — an artefact of `DEFAULT_ORG_ID`
         existing rather than a rule anyone chose.
      2. Seeded into nobody. Even, and broken: a new account opened onto an empty list,
         pressed Search, and nothing happened with no explanation anywhere.
      3. Seeded into everybody, which fixed (2) at the cost of handing a Chicago
         nonprofit 58 San Diego foundations they never asked for and had to prune.

    Now: **nobody, again — but the thing that made (2) broken is gone.** Onboarding step 3
    is the researched lists as one-click imports, so an empty list is a question being
    asked rather than a dead end; and `runner.preflight` refuses a search with no funders
    and names the page that fixes it, so the silent nothing of (2) cannot happen. A new
    org therefore chooses its own funders, which is the only version of this that is both
    even and correct outside San Diego.

    Settings still reconcile on every boot rather than once: `seed_settings` is INSERT ...
    ON CONFLICT DO NOTHING per key, so a genuinely new setting appears for an existing org
    without touching a value anyone has chosen.
    """
    seed_settings(conn, org_id)


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
        # on opportunities.
        #
        # It also added the cached 990 columns on both tables. Those are gone (v12), and
        # they are removed from here too rather than added-then-dropped: a database that
        # never reached v5 has no reason to grow six columns on the way to losing them.
        # An install that already ran the old v5 still has them, which is what v12 is for.
        for table, cols in (
            ("opportunities", [
                ("application_lead_time_days", "INTEGER"), ("time_to_funds_days", "INTEGER"),
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

    if current < 8:
        # v8 gives back the warmth that was never theirs. `import_starter_list` copied
        # `Source.warm` into every org it seeded, so a nonprofit that signed up this
        # morning opened Discover funders and found eight funders labelled "Existing
        # relationship" — a statement about their organisation that nobody at their
        # organisation had made.
        #
        # Three conditions, all of them narrowing, because this is a write over the
        # user's own data: only the shipped warm sources, only outside the default org
        # (whose warmth is the real, researched thing), and only rows nobody has edited.
        # `update_funder` bumps `updated_at`, so `updated_at = created_at` is a reliable
        # "untouched since it was imported" — an org that ticked the box themselves keeps
        # their tick.
        from dataclasses import replace

        from agent.sources import ALL_SOURCES, sector_for

        for s in ALL_SOURCES:
            if not s.warm:
                continue
            conn.execute(
                "UPDATE funders SET warm=0, sector=? "
                "WHERE id=? AND org_id<>? AND warm=1 AND updated_at=created_at",
                (sector_for(replace(s, warm=False)), _funder_id(s.funder, s.url),
                 DEFAULT_ORG_ID),
            )
        current = 8

    if current < 9:
        # v9 lands two things that both answer "who is this account, really".
        #
        # `orgs.owner_uid` — somebody has to be able to remove a colleague and hand the
        # org on, and until now nobody could, because nothing recorded who created it.
        # Backfilled to the earliest member, which is the person who made it in every
        # case that exists: an org is created by its first user signing in.
        org_cols = {r["name"] for r in conn.execute("PRAGMA table_info(orgs)")}
        if "owner_uid" not in org_cols:
            conn.execute("ALTER TABLE orgs ADD COLUMN owner_uid TEXT")
        conn.execute(
            "UPDATE orgs SET owner_uid = ("
            "  SELECT uid FROM users WHERE users.org_id = orgs.id "
            "  ORDER BY created_at LIMIT 1) "
            "WHERE owner_uid IS NULL")

        # `onboarding_done` — an org that has already been used is not new, whatever its
        # settings happen to look like today. Without this backfill the flag lands as 0
        # and every established account is shown the first-run walkthrough on its next
        # visit, which is a worse version of the bug it was added to fix.
        #
        # **"Has been used", not "exists".** The obvious version of this marked every row
        # in `orgs`, and on a brand-new install that is wrong: the v7 migration above
        # creates `DEFAULT_ORG_ID` itself, seconds earlier, so a first-ever boot marked
        # its own default org as an experienced user and nobody ever saw onboarding at
        # all. Evidence of use is a member, a finding, or a saved API key — the pilot org
        # has all three, a long-running local install has the latter two, and a database
        # created thirty milliseconds ago has none.
        #
        # Runs before `seed_settings`, whose INSERT ... ON CONFLICT DO NOTHING then leaves
        # these values alone. Orgs created after this migration get the 0 default and see
        # the walkthrough once, which is the point.
        stamp = now_iso()
        used = conn.execute(
            "SELECT id FROM orgs WHERE"
            "  EXISTS (SELECT 1 FROM users WHERE users.org_id = orgs.id)"
            "  OR EXISTS (SELECT 1 FROM runs WHERE runs.org_id = orgs.id)"
            "  OR EXISTS (SELECT 1 FROM opportunities WHERE opportunities.org_id = orgs.id)"
            "  OR EXISTS (SELECT 1 FROM settings s WHERE s.org_id = orgs.id"
            "             AND s.key = 'anthropic_api_key' AND s.value IS NOT NULL)"
        ).fetchall()
        for row in used:
            conn.execute(
                "INSERT INTO settings(org_id, key, value, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(org_id, key) DO NOTHING",
                (row["id"], "onboarding_done", "1", stamp))
        if used:
            log.info("v9: %d org(s) already in use — not showing them onboarding",
                     len(used))
        current = 9

    if current < 10:
        # v10 records how each funder got onto a list, which nothing did before.
        #
        # It matters now for two reasons that both come down to the same distinction: a
        # copy of a list we ship is not somebody's work. Only hand-added funders survive
        # an org closing, and only hand-added funders are ever offered to another
        # nonprofit — re-sharing the San Diego list back to people who can already import
        # it contributes nothing.
        #
        # Backfilled by id, which is reliable because the two insert paths compute it
        # differently: `import_starter_list` uses `_funder_id(name, url)`, and
        # `repo.create_funder` hashes the name alone. So a row whose id matches a shipped
        # source's derived id came from the shipped list, and everything else was typed.
        funder_cols = {r["name"] for r in conn.execute("PRAGMA table_info(funders)")}
        for col, decl in (("added_by", "TEXT NOT NULL DEFAULT 'user'"),
                          ("check_ok", "INTEGER"),
                          ("check_note", "TEXT NOT NULL DEFAULT ''"),
                          ("checked_at", "TEXT")):
            if col not in funder_cols:
                conn.execute(f"ALTER TABLE funders ADD COLUMN {col} {decl}")

        from agent.sources import ALL_SOURCES

        shipped = {_funder_id(s.funder, s.url) for s in ALL_SOURCES}
        if shipped:
            marks = ",".join("?" * len(shipped))
            n = conn.execute(
                f"UPDATE funders SET added_by='starter' WHERE id IN ({marks})",
                tuple(shipped)).rowcount
            log.info("v10: %d funder row(s) came from a shipped list", n)
        current = 10

    if current < 11:
        # v11 forgets every *failed* check so the new rule gets to look again.
        #
        # The old one counted distinct surface forms of grant vocabulary and wanted
        # three, which rejected the MacArthur Foundation's grant-search page: real text,
        # a page titled "Grant Search", a stated figure, and a vocabulary of "grant" and
        # "grants" — two strings, one word. Anything turned away by that verdict deserves
        # a second look rather than being marked unshareable for good.
        #
        # Only failures are cleared. A funder that passed is still fine, and re-fetching
        # every page on every heuristic tweak would be a lot of somebody else's bandwidth
        # for no new information.
        cleared = conn.execute(
            "UPDATE funders SET check_ok=NULL, check_note='', checked_at=NULL "
            "WHERE check_ok=0").rowcount
        if cleared:
            log.info("v11: %d funder(s) will be checked again under the new rule", cleared)
        current = 11

    if current < 12:
        # v12 removes the cached IRS 990 data and the lookup behind it.
        #
        # It was a third-party dependency (ProPublica's Nonprofit Explorer) bought for
        # two things, and it was the wrong price for both. It put one line — the funder's
        # revenue and expenses — into the Sonnet prompt, under an instruction to judge
        # PROGRAM FIT from the funder's "past grants", which the lookup never returns and
        # the model therefore never saw. And it did so for only about half the list: a
        # county agency, a state arts council and a fund inside a community foundation
        # file no 990 at all, so two near-identical grants could score differently for a
        # reason that had nothing to do with either grant.
        #
        # Dropped rather than left dead, so the next person reading `funders` does not
        # find six columns nothing writes. `DROP COLUMN` needs SQLite 3.35 (2021); where
        # it is older the values are nulled instead, which reaches the same place — no
        # 990 data, nothing reading it — with a wider schema. Neither outcome is worth
        # failing a boot over, so the whole thing is best-effort.
        for table, cols in (
            ("funders", ("ein", "form_990_url", "form_990_year",
                         "form_990_total_revenue", "form_990_total_expenses",
                         "form_990_checked_at")),
            ("opportunities", ("ein", "form_990_url", "form_990_year",
                               "form_990_total_revenue", "form_990_total_expenses",
                               "form_990_available")),
        ):
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col in cols:
                if col not in have:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
                except sqlite3.OperationalError as exc:
                    log.info("v12: leaving %s.%s in place (%s) — nothing reads it",
                             table, col, exc)
                    conn.execute(f"UPDATE {table} SET {col}=NULL")
        current = 12

    if current < 13:
        # v13 adds the per-candidate reject log behind the stage boxes, plus the two
        # tier counts and the per-tier cost split.
        #
        # Nothing backfills. A run that finished before this existed genuinely has no
        # per-candidate record — the detail was logged at DEBUG and thrown away — and
        # inventing rows from `rejected_by_filter` counts would put funder names on a
        # page that were never checked against anything.
        run_cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
        for col, decl in (("rejects", "TEXT NOT NULL DEFAULT '[]'"),
                          ("triaged", "INTEGER NOT NULL DEFAULT 0"),
                          ("scored", "INTEGER NOT NULL DEFAULT 0"),
                          ("usd_by_stage", "TEXT NOT NULL DEFAULT '{}'")):
            if col not in run_cols:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")
        current = 13

    if current < 14:
        # v14 separates blocking from pausing. Nothing is migrated INTO it: every
        # existing `active=0` row is a pause, because pausing is all the UI could
        # express, and promoting them to blocks would silently stop researched lists
        # offering funders that people had only set aside for the season.
        funder_cols = {r["name"] for r in conn.execute("PRAGMA table_info(funders)")}
        if "blocked" not in funder_cols:
            conn.execute("ALTER TABLE funders ADD COLUMN blocked "
                         "INTEGER NOT NULL DEFAULT 0")
        current = 14

    if current < 15:
        # v15 makes a score decomposable, and stops a missing award amount from reading
        # as a bad grant.
        #
        # **Nothing is backfilled, and old rows are not rescored.** A run that finished
        # before this existed returned one holistic integer and there is no honest way to
        # split it into three — inventing components would put numbers on a page that no
        # model ever produced, which is the same rule §6 applies to award amounts.
        #
        # So rows written before v15 keep their total and show no breakdown. They age out
        # on their own: findings are partitioned by `month_key` and every run purges the
        # org's earlier months. The one real cost is a window where this month's scores
        # and last month's are on different scales, which is why the UI labels a
        # renormalised score with what it was scored on rather than presenting a bare
        # number that quietly changed meaning.
        opp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
        for col in ("fit_score", "award_score", "timing_score"):
            if col not in opp_cols:
                conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} INTEGER")
        current = 15

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
        # Only carry across columns the *current* schema still has. A column that has
        # since been removed (the 990 cache, v12) is still sitting in a database that
        # stopped at v5, and naming it here would make the INSERT fail with "no such
        # column" — an upgrade that dies halfway rather than a column quietly dropped.
        # Intersecting keeps this migration correct as the schema keeps moving.
        live = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        names = ", ".join(c for c in cols if c in live)
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
    # You administer what you created. Claimed rather than assigned, so adopting the
    # pre-tenancy org (which may already have an owner from the v9 backfill) does not
    # quietly depose whoever holds it.
    conn.execute("UPDATE orgs SET owner_uid=? WHERE id=? AND owner_uid IS NULL",
                 (uid, org_id))
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


def redeem_invite(conn: sqlite3.Connection, code: str, uid: str, email: str) -> dict:
    """Move (or place) this person into the org the code belongs to.

    Redeeming is idempotent per person but single-use per code: the second person to try
    the same code is told to ask for their own. The error messages deliberately do not
    distinguish "no such code" from "already used" beyond what the holder needs to act —
    there is nothing to enumerate here, but there is also no reason to be chatty.

    **Joining MOVES you, so leaving is governed by the same rules as closing an account**
    (`main.delete_own_account`), and for the same reasons. This used to be a bare
    `UPDATE users SET org_id`, which walked straight past both of them:

      - An admin with colleagues could leave, and the last person who could invite or
        remove anybody was gone. The org was frozen with no way to unfreeze it.
      - Somebody leaving an org they were alone in left it with no members and everything
        still in it — findings, and an encrypted API key that is a live credential
        attached to an account nobody can sign into.

    So the caller goes out through `remove_member`, which strands a now-empty org (see
    `strand_org`: findings, run log and key deleted; hand-added funders kept) and re-seats
    the owner if it was them. The refusal is the only case where nothing happens at all.

    Ordering matters: everything that can refuse is checked BEFORE the code is marked
    redeemed. Marking first and raising after would burn a single-use invitation on an
    attempt that did nothing, and the holder would have to ask for another one.

    Returns what happened, because the caller has to be told: {org_id, left_org,
    stranded}. `stranded` true means their previous org's findings and key are gone.
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
    existing = conn.execute("SELECT uid, org_id FROM users WHERE uid=? OR email=?",
                            (uid, email)).fetchone()
    old_org = existing["org_id"] if existing else None

    # Already there. Not an error — somebody re-pasting a code they have used should be
    # told they are in, not told off — but the invitation is not spent on it either.
    if old_org == org_id:
        return {"org_id": org_id, "left_org": None, "stranded": False}

    stranded = False
    if old_org:
        others = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE org_id=? AND uid<>?",
            (old_org, existing["uid"])).fetchone()["n"]
        if others and org_owner(conn, old_org) == existing["uid"]:
            raise InviteError(
                "You are the admin of the organization you are in now, and other people "
                "are still in it. Hand it over to one of them from Settings first — "
                "otherwise nobody left could invite or remove anyone.")
        stranded = not others

    now = now_iso()
    conn.execute("UPDATE invites SET redeemed_at=?, redeemed_by=? WHERE code=?",
                 (now, email, code))

    if existing:
        # Out through the same door as closing an account, rather than a bare reassign.
        remove_member(conn, existing["uid"], old_org)
    conn.execute(
        "INSERT INTO users(uid, email, org_id, created_at, last_seen_at) "
        "VALUES(?,?,?,?,?)", (uid, email, org_id, now, now))

    log.info("%s joined org %s by invitation (left %s, stranded=%s)",
             email, org_id, old_org or "no org", stranded)
    return {"org_id": org_id, "left_org": old_org, "stranded": stranded}


def org_members(conn: sqlite3.Connection, org_id: str) -> list[dict]:
    owner = org_owner(conn, org_id)
    return [{**dict(r), "is_admin": bool(owner) and r["uid"] == owner}
            for r in conn.execute(
                "SELECT uid, email, created_at, last_seen_at FROM users WHERE org_id=? "
                "ORDER BY created_at", (org_id,))]


def org_owner(conn: sqlite3.Connection, org_id: str) -> str | None:
    """The uid who administers this org, healing the record if it has gone stale.

    Self-healing matters more than it looks. An owner who deletes their own account, or
    an org migrated in from before ownership existed, leaves `owner_uid` pointing at
    nobody — and an org with members but no owner can never remove anybody or hand
    itself on again. So a dangling owner falls through to the earliest remaining member,
    which is the same rule the v9 backfill used and the same person a human would pick.
    """
    row = conn.execute("SELECT owner_uid FROM orgs WHERE id=?", (org_id,)).fetchone()
    owner = row["owner_uid"] if row else None
    if owner and conn.execute(
            "SELECT 1 FROM users WHERE uid=? AND org_id=?", (owner, org_id)).fetchone():
        return owner

    heir = conn.execute(
        "SELECT uid FROM users WHERE org_id=? ORDER BY created_at LIMIT 1",
        (org_id,)).fetchone()
    if heir is None:
        return None
    conn.execute("UPDATE orgs SET owner_uid=? WHERE id=?", (heir["uid"], org_id))
    log.info("org %s had no valid owner — %s inherits it", org_id, heir["uid"])
    return heir["uid"]


def set_org_owner(conn: sqlite3.Connection, org_id: str, uid: str) -> None:
    """Hand the org to another of its members. Caller checks who is asking."""
    if not conn.execute("SELECT 1 FROM users WHERE uid=? AND org_id=?",
                        (uid, org_id)).fetchone():
        raise ValueError("that person is not in this organization")
    conn.execute("UPDATE orgs SET owner_uid=? WHERE id=?", (uid, org_id))
    log.info("org %s handed to %s", org_id, uid)


def remove_member(conn: sqlite3.Connection, uid: str, org_id: str) -> bool:
    """Take one person out of an org. Returns False if they were not in it.

    Deleting the `users` row *is* the revocation, and it is complete: every `/api` route
    resolves the caller's org through `org_for_user`, so with no row there is no org to
    resolve and nothing of this org's — findings, funders, the encrypted API key — is
    reachable by them again. Their next sign-in provisions a fresh empty org, which is
    the "they see onboarding like a new user" the removal is supposed to produce.

    If they were the last one out, the org is stranded rather than deleted — see
    `strand_org` for what that keeps and what it does not.
    """
    cur = conn.execute("DELETE FROM users WHERE uid=? AND org_id=?", (uid, org_id))
    if not cur.rowcount:
        return False
    if not conn.execute("SELECT 1 FROM users WHERE org_id=? LIMIT 1",
                        (org_id,)).fetchone():
        strand_org(conn, org_id)
    else:
        org_owner(conn, org_id)      # re-seat the owner if that was them
    return True


def strand_org(conn: sqlite3.Connection, org_id: str) -> dict[str, int]:
    """Nobody is left in this org. Throw away what is theirs; keep what is not.

    **Deleted** — the month's findings, the run log, and any unused invitations, because
    they are one nonprofit's private research and nobody can ever ask for them again. And
    the encrypted API key, which is the part that would otherwise be a live credential
    sitting in a table attached to an account with no owner.

    **Kept — deliberately — the funders they added by hand, and only those.** A funder
    is not private: it is a name, a grants page and a sector, and a hand-added one is
    researched work that the next nonprofit in that city can use. The imported ones go
    with everything else, because a copy of a list we already ship to everybody is not a
    contribution and keeping it would just leave duplicates lying around.

    Settings stay too, `org_name` above all, because attributing that funder list later
    needs to know whose it was.

    The org row itself is not deleted: `funders.org_id` and `settings.org_id` point at
    it, and an orphan row costs nothing next to losing the reason for keeping them.
    """
    counts = {}
    for table in ("opportunities", "runs"):
        counts[table] = conn.execute(
            f"DELETE FROM {table} WHERE org_id=?", (org_id,)).rowcount
    counts["imported_funders"] = conn.execute(
        "DELETE FROM funders WHERE org_id=? AND added_by='starter'", (org_id,)).rowcount
    counts["invites"] = conn.execute(
        "DELETE FROM invites WHERE org_id=? AND redeemed_at IS NULL",
        (org_id,)).rowcount
    counts["api_key"] = conn.execute(
        "DELETE FROM settings WHERE org_id=? AND key='anthropic_api_key'",
        (org_id,)).rowcount
    conn.execute("UPDATE orgs SET owner_uid=NULL WHERE id=?", (org_id,))

    kept = conn.execute("SELECT COUNT(*) AS n FROM funders WHERE org_id=?",
                        (org_id,)).fetchone()["n"]
    log.info("org %s has no members left — cleared %s, kept %d funder(s)",
             org_id, counts, kept)
    counts["funders_kept"] = kept
    return counts


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

    **Warmth is never imported, and that is a correctness rule, not a preference.**
    `Source.warm` records that *the pilot organisation* already receives money from that
    funder. Copied verbatim into every new org, it printed "Existing relationship" on
    eight funders a nonprofit that signed up this morning has never spoken to — a claim
    about them, made by us, on their own funder page. Whether a relationship exists is
    something only that org can say, so they say it: the tick is on the funder editor,
    and it starts unticked. The sector is derived the same way, since `sector_for` reads
    warmth and would otherwise file them under "Partners we already work with".
    """
    from dataclasses import replace

    from agent.directory import get as get_list
    from agent.sources import sector_for

    lst = get_list(key)
    if lst is None:
        raise ValueError(f"no starter list called {key!r}")

    # A blocked funder is never re-offered. `ON CONFLICT DO NOTHING` already protects a
    # row that exists, but blocking is supposed to mean "and stop suggesting this" — and
    # deleting a blocked row then importing the list would put it straight back.
    blocked = {r["id"] for r in
               conn.execute("SELECT id FROM funders WHERE blocked=1 AND org_id=?",
                            (org_id,))}

    stamp = now_iso()
    added = 0
    for s in lst.sources:
        if _funder_id(s.funder, s.url) in blocked:
            continue
        cold = replace(s, warm=False)
        cur = conn.execute(
            """INSERT INTO funders(
                   org_id, id, name, url, sector, funder_type, warm, active,
                   exclude_reason, tier, confidence, programs, adapter, notes,
                   added_by, created_at, updated_at)
               VALUES(?,?,?,?,?,?,0,1,'',?,?,?,?,?,'starter',?,?)
               ON CONFLICT(org_id, id) DO NOTHING""",
            (org_id, _funder_id(s.funder, s.url), s.funder, s.url, sector_for(cold),
             _funder_type_for(s), int(s.tier), int(s.confidence),
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
