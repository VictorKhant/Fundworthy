"""SQLite store — schema, connections, migrations. (docs/PLAN.md §2b)

One file on disk, no server, no ORM. The whole store is small enough to read in one
sitting, which matters more than elegance for something RISE has to maintain after we
leave.

Four things live here that used to live in a Google Sheet or in Python source:

  settings       the award floor, the runway, the caps, the kill switch, the API key
  programs       RISE's programs as editable cards, ticked on or off per week
  funders        the partner list, editable — no longer hardcoded in agent/sources.py
  opportunities  this month's findings, which is also the dedup index and the archive
  runs           the run log

On dedup and the monthly purge
------------------------------
`opportunities.id` is a TEXT PRIMARY KEY holding `stable_id(source_url, title)`. SQLite
backs a TEXT PRIMARY KEY with a unique index, so "have we already shown Mauri this?" is
an index probe, not a scan — constant time in practice regardless of how many rows the
month accumulated. That check runs in the free deterministic tier, so a repeat finding
costs $0.00 rather than a Haiku call.

The purge is deliberately blunt: at the start of every run, every row from a month
earlier than the current one is deleted. That keeps the file from growing without bound
and means a grant seen in July is allowed to resurface in August. That resurfacing is
intended, not a bug — it is the documented exception (docs/PLAN.md §2b).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/rise.db")

SCHEMA_VERSION = 4

# --- schema -------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS programs (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
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
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT,
    sector      TEXT NOT NULL DEFAULT 'other',
    funder_type TEXT NOT NULL DEFAULT 'other',
    -- An existing RISE relationship. Kept as a LABEL only. It used to boost the score
    -- and sort first; the stakeholder has since said the opposite — they already get
    -- money from those funders consistently and do not want to reapply — so warmth is
    -- now a reason to consider EXCLUDING, never a reason to rank higher.
    warm        INTEGER NOT NULL DEFAULT 0,
    -- The remove list. Unticked = never fetched, never triaged, never scored. This is
    -- the whole point: excluding at the crawl stage costs nothing, where excluding
    -- after scoring would have already spent the tokens.
    active      INTEGER NOT NULL DEFAULT 1,
    exclude_reason TEXT NOT NULL DEFAULT '',  -- why she took it off the list
    tier        INTEGER NOT NULL DEFAULT 1,
    confidence  INTEGER NOT NULL DEFAULT 1,   -- agent.sources.Confidence
    programs    TEXT NOT NULL DEFAULT '[]',   -- json array of program slugs
    -- Key into agent/apis.py ADAPTERS. NULL means "crawl the HTML". Stored rather
    -- than re-derived, because a source that loses its adapter silently becomes an
    -- ordinary web page and stops being read at all.
    adapter     TEXT,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id                     TEXT PRIMARY KEY,   -- stable_id(source_url, title)
    run_id                 TEXT,
    month_key              TEXT NOT NULL,      -- 'YYYY-MM' — the purge + dedup partition
    found_on               TEXT NOT NULL,      -- date first surfaced to Mauri
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
    -- different starting positions for a conversation, so Mauri gets to see which.
    source_kind            TEXT NOT NULL DEFAULT 'funder_page',
    fetched_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opp_month ON opportunities(month_key);
CREATE INDEX IF NOT EXISTS idx_opp_run   ON opportunities(run_id);

CREATE TABLE IF NOT EXISTS runs (
    id                 TEXT PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""


# --- defaults -----------------------------------------------------------------

# §11 Q1 is ANSWERED: $10,000 is the smallest award worth 10 hours of team time.
# The placeholder machinery that used to guard this is gone (docs/PLAN.md §0).
MIN_AWARD_DEFAULT = 10_000

DEFAULT_SETTINGS: dict[str, str] = {
    "min_award": str(MIN_AWARD_DEFAULT),
    "min_deadline_runway_days": "14",
    "max_opportunities": "12",
    "run_budget_usd": "1.00",
    "enabled": "1",
    # The taxonomy is a placeholder until Mauri answers STAKEHOLDER.md Q10 ("what are
    # the four sectors?"). Her answer renames labels; it does not change code.
    "sectors_active": json.dumps(
        ["warm_partner", "foundation", "government", "arts_agency"]
    ),
    "search_beyond_partners": "0",  # lights up once the discovery provider lands
}

SECTORS = ("warm_partner", "foundation", "government", "arts_agency",
           "intermediary", "corporate", "other")

FUNDER_TYPES = ("private_foundation", "corporate", "community", "government",
                "public_agency", "other", "unknown")


# --- connection ---------------------------------------------------------------

def db_path() -> Path:
    return Path(os.environ.get("RISE_DB_PATH") or DEFAULT_DB_PATH)


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
        if seed:
            seed_settings(conn)
            seed_programs(conn)
            seed_funders(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Forward-only migrations keyed off meta.schema_version.

    There is exactly one version today. The hook exists so that adding a column after
    RISE is already running does not mean asking someone to delete their database.
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

    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(current),),
    )


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

def seed_settings(conn: sqlite3.Connection) -> None:
    """Insert defaults for any setting not already present. Never overwrites."""
    stamp = now_iso()
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO NOTHING",
            (key, value, stamp),
        )


# RISE's programs, with the URLs confirmed by fetching risesandiego.org/programs.
#
# Only the three Mauri named as priorities ship with content, and that content comes
# from CLAUDE.md §7 — i.e. from the intake conversation, not from us. The other four
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
    # --- named by RISE, not yet described. The assistant fills these in. ---
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


def seed_programs(conn: sqlite3.Connection) -> None:
    """First boot only. Never overwrites a card Mauri has edited."""
    stamp = now_iso()
    for p in SEED_PROGRAMS:
        conn.execute(
            """INSERT INTO programs(
                   id, name, slug, summary, what_it_funds, keywords, funder_types,
                   search_queries, min_award, active, source_url, drafted_by_ai,
                   reviewed_by_human, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?,?)
               ON CONFLICT(slug) DO NOTHING""",
            (
                p["slug"].lower(), p["name"], p["slug"],
                p.get("summary", ""), p.get("what_it_funds", ""),
                dumps(p.get("keywords", [])), dumps(p.get("funder_types", [])),
                dumps(p.get("search_queries", [])), p.get("min_award"),
                int(p.get("active", 0)), p.get("source_url", ""),
                stamp, stamp,
            ),
        )


def seed_funders(conn: sqlite3.Connection) -> None:
    """Seed the partner list from agent/sources.py on first boot.

    The registry stays in agent/sources.py as the shipped starting point — deleting it
    would collide with the teammate's discovery branch and would lose the URL-confidence
    research already done there. From here on the DB is authoritative: Mauri adds,
    edits, and deactivates partners in the dashboard, and a funder who stops funding
    RISE gets deactivated rather than deleted, so the relationship history survives.
    """
    from agent.sources import ALL_SOURCES, sector_for

    stamp = now_iso()
    for s in ALL_SOURCES:
        conn.execute(
            """INSERT INTO funders(
                   id, name, url, sector, funder_type, warm, active, tier,
                   confidence, programs, adapter, notes, created_at, updated_at)
               VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   -- Only ever backfill the adapter. Everything else on an existing
                   -- row is Mauri's, and a re-seed must not overwrite her edits.
                   adapter=COALESCE(funders.adapter, excluded.adapter)""",
            (
                _funder_id(s.funder, s.url), s.funder, s.url, sector_for(s),
                _funder_type_for(s), int(s.warm), int(s.tier), int(s.confidence),
                dumps([p.value for p in s.programs]), s.adapter, s.notes, stamp, stamp,
            ),
        )


def _funder_id(name: str, url: str | None = None) -> str:
    """Seed identity for a registry entry: name AND url.

    Name alone is not unique. Grants.gov and SAM.gov are both `funder="U.S. Federal
    Government"` in sources.py, so hashing the name collapsed them into one row and
    SAM.gov vanished from the registry with no error anywhere — the seed just wrote
    over itself. Including the URL keeps distinct entries distinct.

    (`create_funder` still keys on name alone, deliberately: when Mauri types a funder
    that is already on her list, updating that row is what she means, not adding a
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
