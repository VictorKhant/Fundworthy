"""Runtime configuration. (CLAUDE.md)

Where config lives changed. CLAUDE.md put it in a Google Sheets tab and §3 called
editing it in the dashboard a non-goal; both are deliberately reversed, because what
the user actually asked for — tick these programs, with these search terms, at this floor,
this week — is not a thing a spreadsheet cell can express.

Resolution order, most authoritative first:

  1. **SQLite** (`data/rise.db`) — what the dashboard writes. The normal path.
  2. **The Google Sheet** — kept as a fallback so the existing scheduled job and anyone
     already using the Config tab keep working through the transition.
  3. **Shipped defaults** — so the agent stays runnable from a fresh clone with no
     database, no Sheet and no key.

The kill switch keeps its §8 guarantee in every one of those cases: under
`FUNDWORTHY_STRICT_CONFIG` a config we cannot read is a refusal to run, never a silent
fallback to `enabled=True`. The direction of that failure is the whole point — a
transient outage must not be able to swallow the user's decision to turn the agent off.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from .sources import Tier

log = logging.getLogger(__name__)

CONFIG_TAB = "Config"

# CLAUDE.md Q1 — ANSWERED. $10,000 is the smallest award the organization considers worth ten
# collective hours of team time. This used to be a $25,000 placeholder wrapped in
# machinery that shouted "not a real answer" on every run; that machinery is gone,
# because the question it was guarding is closed.
MIN_AWARD_DEFAULT = 10_000


@dataclass
class ProgramCard:
    """One of the organization's programs, as the user edits it in the dashboard.

    This replaces the hardcoded three-value `Program` enum as the unit of "what are we
    searching for". Seven programs exist; they tick the ones that matter this week.
    """

    slug: str
    name: str
    summary: str = ""
    what_it_funds: str = ""
    keywords: list[str] = field(default_factory=list)
    funder_types: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    min_award: int | None = None   # per-program override of the global floor

    def floor(self, global_min: int) -> int:
        return self.min_award if self.min_award is not None else global_min

    @property
    def is_described(self) -> bool:
        """Has anyone actually said what this program is looking for?

        The four non-priority cards ship with a name and a real URL and nothing else,
        because inventing a description of a real organisation's programme is the
        failure §6 forbids for award amounts. Ticking one of those is a real state, and
        every search path has to handle it by saying so rather than by guessing.
        """
        return bool(self.keywords or self.search_queries)

    def api_vocabulary(self, default: str | None = None) -> str | None:
        """Search terms for a keyword API, or None if this card can't supply any.

        Order matters. A keyword API wants a handful of words: `search_queries` are
        written for a general web search ("arts and social justice grant California")
        and over-narrow a federal index that has no notion of California, so a curated
        `default` for a program we already tuned wins over them. Cards the user creates
        have no default, so their own keywords drive the search — which is the whole
        point of making the cards editable.
        """
        if default:
            return default
        if self.keywords:
            # Capped: a query built from every phrase on the card matches nothing.
            return " ".join(self.keywords[:4])
        if self.search_queries:
            return self.search_queries[0]
        return None


DEFAULT_PROGRAMS = [
    ProgramCard(slug="RULFP", name="RISE Urban Leadership Fellows Program"),
    ProgramCard(slug="RESILIENCE", name="RISE Resilience & Renewal"),
    ProgramCard(slug="ARTS", name="RISE Arts"),
]


@dataclass
class Config:
    """Runtime settings, whatever they were read from."""

    enabled: bool = True                     # the kill switch (§8)
    min_award: int = MIN_AWARD_DEFAULT       # §11 Q1, answered
    max_opportunities: int = 12              # sized for a 1-hour review (§9)
    programs: list[ProgramCard] = field(default_factory=lambda: list(DEFAULT_PROGRAMS))
    sectors_active: list[str] = field(
        default_factory=lambda: ["warm_partner", "foundation", "government", "arts_agency"]
    )
    search_beyond_partners: bool = False     # lights up when a DiscoveryProvider lands
    run_day: str = "Wednesday"
    run_time: str = "23:00"
    max_tier: Tier = Tier.WARM
    # Balanced mode: take at most this many from each source kind (funder pages vs
    # indexed databases) instead of one combined cap. Off by default — see the design
    # note in §8: a per-kind quota makes the agent pad a thin category rather than
    # report that the category was thin, which is the failure the cap exists to avoid.
    per_kind_cap: int | None = None
    weekly_budget_usd: float = 1.00          # hard ceiling (§8)
    min_deadline_runway_days: int = 14       # reject inside this window (§7)
    source: str = "defaults"                 # "database" | "sheet" | "defaults"
    # Whose run this is. Carried on the config rather than threaded through every
    # function signature because every stage of the pipeline already receives a Config,
    # and the org is exactly what a config *is* — one nonprofit's settings, cards,
    # funders and key. Defaults to the single-tenant org so the CLI and the tests keep
    # working unchanged.
    org_id: str = "default"

    @property
    def programs_active(self) -> list[str]:
        """Active program slugs. Kept as plain strings so a program the user invents in
        the dashboard is a first-class citizen, not something the pipeline drops
        because it is missing from a Python enum."""
        return [p.slug for p in self.programs]

    @property
    def effective_min_award(self) -> int:
        """The floor the deterministic filter should use.

        The LOWEST floor across active programs, not the global one. If RISE Arts will
        take $5,000 while everything else needs $10,000, filtering the crawl at $10,000
        would throw away Arts opportunities before any program-aware scoring ever sees
        them. The per-program floor is then applied again during scoring, where we know
        which program a candidate actually matches.
        """
        floors = [p.floor(self.min_award) for p in self.programs]
        return min(floors) if floors else self.min_award

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        if not self.programs:
            out.append(
                "No programs are ticked, so there is nothing to search for. Tick at "
                "least one program card on the dashboard."
            )
        if self.source == "defaults":
            out.append(
                "Running on shipped defaults — no database and no Sheet was readable. "
                "Nothing the user set in the dashboard is being applied."
            )
        return out


# --- parsing helpers ----------------------------------------------------------

_TRUE = {"true", "yes", "y", "1", "on", "enabled"}
_FALSE = {"false", "no", "n", "0", "off", "disabled"}


def _as_bool(value, default: bool) -> bool:
    v = str(value).strip().casefold()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _as_int(value, default: int) -> int:
    """Tolerant of what a person actually types: '$10,000', '10k', '10 000'."""
    v = str(value).strip().casefold().replace("$", "").replace(",", "").replace(" ", "")
    if not v:
        return default
    mult = 1
    if v.endswith("k"):
        v, mult = v[:-1], 1_000
    elif v.endswith("m"):
        v, mult = v[:-1], 1_000_000
    try:
        return int(float(v) * mult)
    except ValueError:
        log.warning("Config: could not read %r as a number, using %s", value, default)
        return default


class ConfigUnavailable(RuntimeError):
    """Config could not be read while running in strict mode."""


# --- the database path (the normal one) ---------------------------------------

def load_from_db(db_path=None, *, org_id: str | None = None) -> Config | None:
    """Read settings and active program cards out of SQLite. None if unavailable.

    `org_id` decides whose settings and whose program cards this run uses. Unscoped, a
    run read every org's active cards at once and sent them all to Anthropic in one system
    prompt — one nonprofit's program strategy going out on another's API key.
    """
    try:
        from app.db import DEFAULT_ORG_ID
        from app.db import db_path as default_db_path
        from app.db import session
        from app.repo import get_settings, list_programs
    except ImportError as exc:  # noqa: BLE001 — running the agent without the app package
        log.debug("app package unavailable (%s)", exc)
        return None

    scope = org_id or DEFAULT_ORG_ID
    target = db_path or default_db_path()
    if db_path is None and not default_db_path().exists():
        return None

    try:
        with session(target) as conn:
            settings = get_settings(conn, org_id=scope)
            cards = list_programs(conn, org_id=scope, active_only=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read the settings database (%s)", exc)
        return None

    cfg = Config(source="database", org_id=scope)
    cfg.enabled = bool(settings["enabled"])
    cfg.min_award = int(settings["min_award"])
    cfg.max_opportunities = int(settings["max_opportunities"])
    cfg.weekly_budget_usd = float(settings["run_budget_usd"])
    cfg.min_deadline_runway_days = int(settings["min_deadline_runway_days"])
    cfg.sectors_active = list(settings["sectors_active"])
    cfg.search_beyond_partners = bool(settings["search_beyond_partners"])
    cfg.programs = [
        ProgramCard(
            slug=c["slug"], name=c["name"], summary=c.get("summary", ""),
            what_it_funds=c.get("what_it_funds", ""),
            keywords=list(c.get("keywords") or []),
            funder_types=list(c.get("funder_types") or []),
            search_queries=list(c.get("search_queries") or []),
            min_award=c.get("min_award"),
        )
        for c in cards
    ]
    # Government sources are a real scope decision (§11 Q3), and the answer is yes —
    # the user wants RFPs and contracts too. Ticking the sector is what turns them on.
    cfg.max_tier = Tier.GOVERNMENT if "government" in cfg.sectors_active else (
        Tier.INTERMEDIARY if "intermediary" in cfg.sectors_active else Tier.WARM
    )
    return cfg


# --- the Sheet path (kept as a fallback) --------------------------------------

def load_from_sheet(sheet_id: str, credentials_path: str) -> Config:
    """Read the legacy Config tab. Raises on any failure; the caller decides."""
    import gspread

    gc = gspread.service_account(filename=credentials_path)
    tab = gc.open_by_key(sheet_id).worksheet(CONFIG_TAB)
    raw = {
        str(row[0]).strip().upper(): str(row[1]).strip()
        for row in tab.get_all_values()
        if len(row) >= 2 and row[0]
    }

    cfg = Config(source="sheet")
    cfg.enabled = _as_bool(raw.get("ENABLED", ""), cfg.enabled)
    cfg.min_award = _as_int(raw.get("MIN_AWARD", ""), cfg.min_award)
    cfg.max_opportunities = _as_int(raw.get("MAX_OPPORTUNITIES", ""), cfg.max_opportunities)
    cfg.run_day = raw.get("RUN_DAY") or cfg.run_day
    cfg.run_time = raw.get("RUN_TIME") or cfg.run_time

    if raw.get("PROGRAMS_ACTIVE"):
        wanted = {p.strip().upper() for p in raw["PROGRAMS_ACTIVE"].split(",")}
        chosen = [p for p in DEFAULT_PROGRAMS if p.slug in wanted]
        if chosen:
            cfg.programs = chosen
        else:
            log.warning("PROGRAMS_ACTIVE=%r matched no program — keeping all three.",
                        raw["PROGRAMS_ACTIVE"])
    return cfg


# --- the entrypoint -----------------------------------------------------------

def load_config(sheet_id: str | None = None, credentials_path: str | None = None,
                strict: bool | None = None, db_path=None,
                org_id: str | None = None) -> Config:
    """Resolve config from the database, then the Sheet, then shipped defaults.

    Under `FUNDWORTHY_STRICT_CONFIG` (which the scheduled job sets), reaching the "shipped
    defaults" step is a hard failure rather than a fallback. That is not paranoia: the
    shipped default is `enabled=True`, so a silent fallback means the user sets the kill
    switch to off, a transient outage swallows it, and the agent runs anyway — the one
    failure the kill switch exists to prevent.
    """
    if strict is None:
        strict = os.environ.get("FUNDWORTHY_STRICT_CONFIG", "").strip() in _TRUE

    cfg = load_from_db(db_path, org_id=org_id)
    if cfg is not None:
        log.info("Config: read from the settings database (%s).",
                 db_path or "data/rise.db")
        return cfg

    sheet_id = sheet_id or os.environ.get("FUNDWORTHY_SHEET_ID")
    credentials_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sheet_id and credentials_path:
        try:
            cfg = load_from_sheet(sheet_id, credentials_path)
            log.info("Config: read from the Google Sheet Config tab (legacy path).")
            return cfg
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise ConfigUnavailable(
                    f"Could not read the {CONFIG_TAB} tab ({exc}) and there is no "
                    "settings database. Refusing to run: the kill switch lives in "
                    "config and we cannot confirm it is on."
                ) from exc
            log.warning("Could not read the Config tab (%s).", exc)

    if strict:
        raise ConfigUnavailable(
            "FUNDWORTHY_STRICT_CONFIG is on but no settings database and no readable Config "
            "tab were found. Refusing to run without confirming the kill switch."
        )

    log.info("Config: no database and no Sheet — using shipped defaults.")
    return Config(source="defaults")
