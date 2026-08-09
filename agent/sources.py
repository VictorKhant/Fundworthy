"""The source registry — what the crawler actually visits. (CLAUDE.md Q2)

Tiering is deliberate. Tier 1 is live now; tiers 2 and 3 are registered but disabled
so the crawl scope can be widened by flipping a flag rather than by writing code.

On URL honesty
--------------
§6 says source_url must point at the funder's own page, and that we never state
something we did not read. That rule applies to this file too: a URL nobody has
confirmed is a guess wearing a URL's clothes. Every entry therefore carries an
explicit `confidence`, and entries at UNCONFIRMED are registered but never fetched.
They surface in the run report as research to do, not as silent gaps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

from .models import Program

log = logging.getLogger(__name__)


class Tier(IntEnum):
    """Crawl scope. `active_sources(max_tier)` takes everything at or below max_tier.

    INDEXED is 0 so it is included at every scope, including the default. These are
    complete published lists rather than one funder's marketing page: a single JSON
    request each, no link-following, and they stay up for a structural reason (state
    law, federal infrastructure) rather than because someone remembers to maintain
    them. They are the cheapest and most reliable thing in the registry, so there is
    no scope setting at which it makes sense to skip them.
    """

    INDEXED = 0       # complete lists behind a public API (see apis.py)
    WARM = 1          # the 8 funders the user confirmed warm (§7)
    INTERMEDIARY = 2  # networks and conveners that aggregate opportunities
    GOVERNMENT = 3    # public RFPs and procurement (§11 Q3 — doubles scope)


class Confidence(IntEnum):
    """How much we trust this URL to be the funder's own live grants page."""

    UNCONFIRMED = 0  # we do not know the URL. Never fetched. Reported as a to-do.
    LIKELY = 1       # official domain, plausible path. First run confirms or corrects.
    CONFIRMED = 2    # a run fetched it and found grant content.


@dataclass
class Source:
    name: str
    funder: str
    url: str | None
    tier: Tier
    programs: list[Program] = field(default_factory=list)
    confidence: Confidence = Confidence.LIKELY
    warm: bool = False
    notes: str = ""
    sector: str = ""   # blank => derived by sector_for(); see FUTURE.md
    adapter: str | None = None   # key into apis.ADAPTERS; None means crawl the HTML

    @property
    def is_api(self) -> bool:
        return self.adapter is not None

    @property
    def fetchable(self) -> bool:
        return self.url is not None and self.confidence >= Confidence.LIKELY


def sector_for(source: "Source") -> str:
    """Which funding sector this source belongs to.

    the user named four sectors they want funding found in but we do not yet have the
    list (FUTURE.md). Rather than guess at four names, every source carries a
    sector tag derived from what we already know, and the dashboard exposes them as
    checkboxes. When they give us the real four, this function and the labels change —
    no pipeline code does.
    """
    if source.sector:
        return source.sector
    if source.warm:
        return "warm_partner"
    if source.tier in (Tier.GOVERNMENT, Tier.INDEXED):
        # The two indexed lists are the CA Grants Portal and Grants.gov — state and
        # federal money. Tagging them "government" means the sector checkbox governs
        # them like any other source: if the user unticks government funding, not
        # searching the government's own grant databases is what they asked for.
        return "government"
    if source.tier == Tier.INTERMEDIARY:
        return "intermediary"
    name = source.funder.casefold()
    if "arts" in name or "culture" in name:
        return "arts_agency"
    return "foundation"


# --- Tier 0: the two indexed lists (see apis.py) -------------------------------
#
# Two, not ten. Each additional API is another thing that can break on a Wednesday
# night and another few seconds on the run clock; these two were chosen because
# their uptime rests on statute and federal infrastructure rather than goodwill.

INDEXED_SOURCES: list[Source] = [
    Source(
        name="California Grants Portal",
        funder="State of California",
        url="https://www.grants.ca.gov/",
        tier=Tier.INDEXED,
        programs=[Program.RULFP, Program.RESILIENCE, Program.ARTS],
        adapter="ca_grants_portal",
        notes=(
            "Every CA state agency is required by AB 2252 (2019) to post grant "
            "opportunities here, so this is the closest thing to a complete list of "
            "state money that exists. Read via CKAN on data.ca.gov. One request."
        ),
    ),
    Source(
        name="Grants.gov — federal discretionary grants",
        funder="U.S. Federal Government",
        url="https://www.grants.gov/",
        tier=Tier.INDEXED,
        programs=[Program.RULFP, Program.RESILIENCE, Program.ARTS],
        adapter="grants_gov",
        notes=(
            "The complete federal grant list. Searched once per active program (§7 "
            "says never one search across all three), then a bounded number of detail "
            "lookups to get award ceilings — the field MIN_AWARD actually filters on."
        ),
    ),
]


# --- Tier 1: the eight warm funders (§7, confirmed warm by the user) --------------

WARM_SOURCES: list[Source] = [
    Source(
        name="San Diego Foundation — grant opportunities",
        funder="San Diego Foundation",
        url="https://www.sdfoundation.org/nonprofits/apply-for-a-grant/",
        tier=Tier.WARM,
        programs=[Program.RULFP, Program.RESILIENCE, Program.ARTS],
        confidence=Confidence.CONFIRMED,
        warm=True,
        notes="First run: /nonprofits/grants/ 404s. This is where /grants/ redirects.",
    ),
    Source(
        name="Alliance Healthcare Foundation — Innovation Initiative (i2)",
        funder="Alliance Healthcare Foundation",
        url="https://alliancehf.org/innovation-initiative-i2/",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        warm=True,
        notes=(
            "RISE Resilience & Renewal was born out of AHF's i2 Challenge (§7), so this "
            "is the highest-prior page in the registry. First run: /grants/ 404s; i2 is "
            "the actual open call."
        ),
    ),
    Source(
        name="Prebys Foundation — grants",
        funder="Prebys Foundation",
        url="https://www.prebysfdn.org/grants",
        tier=Tier.WARM,
        programs=[Program.RULFP, Program.ARTS],
        warm=True,
    ),
    Source(
        name="City of San Diego — Economic Development",
        funder="City of San Diego Economic Development",
        url="https://www.sandiego.gov/economic-development",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        warm=True,
    ),
    Source(
        name="City of San Diego — Commission for Arts and Culture",
        funder="City of San Diego Commission for Arts and Culture",
        url="https://www.sandiego.gov/arts-culture/funding",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        warm=True,
    ),
    Source(
        name="California Arts Council — grants",
        funder="California Arts Council",
        url="https://arts.ca.gov/grants/",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        warm=True,
    ),
    Source(
        name="The Morales Fund",
        funder="The Morales Fund",
        url=None,
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.UNCONFIRMED,
        warm=True,
        notes=(
            "URL unknown. Likely a donor-advised or named fund rather than a fund with "
            "its own public grants page — possibly administered through a community "
            "foundation. ASK MAURI: does this fund publish an open call anywhere, or is "
            "it relationship-only? If relationship-only it should leave the crawl "
            "registry and move to the Funders tab as a warmth record."
        ),
    ),
    Source(
        name="The Villegas Fund",
        funder="The Villegas Fund",
        url=None,
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.UNCONFIRMED,
        warm=True,
        notes="URL unknown. Same question as The Morales Fund — ASK MAURI.",
    ),
]


# --- Tier 2: intermediaries and networks (§7) ---------------------------------

INTERMEDIARY_SOURCES: list[Source] = [
    Source(
        name="Catalyst of San Diego & Imperial Counties",
        funder="Catalyst of San Diego & Imperial Counties",
        url="https://catalystsdic.org/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.RULFP, Program.RESILIENCE, Program.ARTS],
        notes="Convener, not usually the funder. Follow through to the funder's own page.",
    ),
    Source(
        name="USD Nonprofit Institute",
        funder="University of San Diego Nonprofit Institute",
        url="https://www.sandiego.edu/soles/nonprofit-institute/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.RULFP],
    ),
    Source(
        name="Live Well San Diego",
        funder="Live Well San Diego",
        url="https://www.livewellsd.org/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.RESILIENCE],
    ),
    Source(
        name="San Diego Regional Arts and Culture Coalition",
        funder="San Diego Regional Arts and Culture Coalition",
        url="https://sdartsandculture.org/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.ARTS],
    ),
]


# --- Tier 3: government RFPs (§11 Q3 — not answered, so not enabled) -----------

GOVERNMENT_SOURCES: list[Source] = [
    Source(
        name="SAM.gov — federal assistance listings",
        funder="U.S. Federal Government",
        url="https://sam.gov/search/?index=opp",
        tier=Tier.GOVERNMENT,
        programs=[Program.RULFP, Program.RESILIENCE],
        confidence=Confidence.UNCONFIRMED,
        notes="JS-rendered search UI — needs the API, not the HTML. Real work, not a URL swap.",
    ),
    Source(
        name="County of San Diego — purchasing and contracting",
        funder="County of San Diego",
        url="https://www.sandiegocounty.gov/content/sdc/purchasing.html",
        tier=Tier.GOVERNMENT,
        programs=[Program.RULFP, Program.RESILIENCE],
        notes=(
            "NOTE: the Equity Impact Grant is a hard reject (§7) — that is one program, "
            "not the whole County. Other County solicitations stay eligible."
        ),
    ),
]


def _researched() -> list[Source]:
    """The 44 researched San Diego funders. Imported lazily to keep this module
    import-light."""
    from .sd_funders import RESEARCHED_SOURCES

    return RESEARCHED_SOURCES


def _ca_family_foundations() -> list[Source]:
    """5 researched California family foundations, outside San Diego."""
    from .ca_family_foundations import RESEARCHED_SOURCES

    return RESEARCHED_SOURCES


def _ca_community_foundations() -> list[Source]:
    """12 researched California community foundations, outside San Diego."""
    from .ca_community_foundations import RESEARCHED_SOURCES

    return RESEARCHED_SOURCES


def _ca_health_foundations() -> list[Source]:
    """6 researched California health foundations, outside San Diego."""
    from .ca_health_foundations import RESEARCHED_SOURCES

    return RESEARCHED_SOURCES


# WARM_SOURCES stays in the registry, but its meaning has changed. The organization already
# receives money from those funders and does not want to reapply, so they are seeded like
# anything else and the user puts the ones they mean on the remove list. They are no longer a
# priority — see agent/sd_funders.py for what replaced them as the actual target.
ALL_SOURCES: list[Source] = (
    INDEXED_SOURCES + WARM_SOURCES + INTERMEDIARY_SOURCES + GOVERNMENT_SOURCES
    + _researched() + _ca_family_foundations() + _ca_community_foundations()
    + _ca_health_foundations()
)


def active_sources(max_tier: Tier = Tier.WARM) -> list[Source]:
    """Sources to check this run. Defaults to the indexed lists plus the warm funders.

    Tier 0 is always in scope — see the Tier docstring for why.
    """
    return [s for s in ALL_SOURCES if s.tier <= max_tier and s.fetchable]


def unconfirmed_sources(max_tier: Tier = Tier.WARM) -> list[Source]:
    """Registered but unfetchable — the run reports these so they don't go quiet."""
    return [s for s in ALL_SOURCES if s.tier <= max_tier and not s.fetchable]


# --- the database-backed registry ---------------------------------------------
#
# The lists above are now the SHIPPED SEED, not the live registry. On first boot they
# are copied into the funders table (app/db.py seed_funders) and from then on the user
# owns the list: they add partners, edit URLs, and — the case that motivated this —
# DEACTIVATE a partner who stops funding the organization, without losing the relationship record.
#
# They stay here rather than being deleted because they carry the URL-confidence
# research from the first crawls (see the notes on each entry), and because a fresh
# clone with no database has to be runnable.

def sources_from_db(max_tier: Tier = Tier.WARM,
                    sectors: list[str] | None = None,
                    db_path=None,
                    org_id: str | None = None) -> tuple[list[Source], list[Source]] | None:
    """(fetchable, unconfirmed) built from the funders table, or None if unavailable.

    `sectors` is the set of sector tags the user ticked for this run. An empty or missing
    list means "no sector filter" rather than "nothing" — silently searching nothing
    would look identical to a quiet week, which is the one ambiguity this project
    cannot afford.
    """
    try:
        from app.db import DEFAULT_ORG_ID
        from app.db import db_path as default_db_path
        from app.db import loads, session
    except ImportError:
        return None

    scope = org_id or DEFAULT_ORG_ID

    target = db_path or default_db_path()
    if db_path is None and not default_db_path().exists():
        return None

    try:
        with session(target) as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM funders WHERE active=1 AND blocked=0 AND org_id=? "
                "ORDER BY warm DESC, name", (scope,))]
    except Exception:
        # Unlike the two branches above, the database *does* exist here — this is a
        # real failure reading it (lock contention from another org's concurrent run,
        # a corrupt row), not the ordinary "fresh clone" case. It still falls back to
        # the shipped registry rather than aborting the run, but it must not be
        # indistinguishable from "no funders database found": that message is false
        # here, and `resolve_sources` (agent/run.py) checks which case this was so the
        # run notes say what actually happened.
        log.error("could not read the funders table at %s — falling back to the "
                  "shipped registry", target, exc_info=True)
        return None

    # --- sector: deliberately not a filter any more (R8) ------------------------
    #
    # This used to be `if wanted and r["sector"] not in wanted: continue`, and the
    # `sectors` argument is now accepted and ignored. Same reasoning as the geography
    # filter in agent/filters.py, which was removed for the same reason rather than
    # fixed:
    #
    #   - The taxonomy is **our guess**. "warm_partner / foundation / government /
    #     arts_agency" is four buckets we invented, and the settings copy admitted it.
    #     A funder's bucket is assigned by `sector_for` from the shipped registry, or
    #     defaulted to "foundation" when somebody types one in — so unticking a box
    #     excluded funders on the strength of a label nobody at the nonprofit chose.
    #   - It failed silently and for free, in the tier that explains nothing. A funder
    #     was simply never fetched, and the only clue was a thinner week.
    #
    # Which funders get searched is decided by the funder list — pause, block, delete —
    # which is a decision the org actually made, one funder at a time, and which the
    # stage boxes now report on.
    #
    # The argument stays in the signature and `sectors_active` stays in the schema, so
    # an old caller and an old settings row both still work.
    fetchable: list[Source] = []
    unconfirmed: list[Source] = []
    for r in rows:
        if int(r["tier"]) > int(max_tier):
            continue
        source = Source(
            name=r["name"],
            funder=r["name"],
            url=r["url"] or None,
            tier=Tier(int(r["tier"])),
            programs=[p for p in loads(r["programs"], [])],
            confidence=Confidence(int(r["confidence"])),
            warm=bool(r["warm"]),
            notes=r["notes"] or "",
            sector=r["sector"],
            # Without this the two indexed lists come back from the database as
            # ordinary HTML sources, `is_api` goes False, and the CA Grants Portal and
            # Grants.gov silently stop being read — a whole class of funding
            # disappearing with no error anywhere. The adapter has to survive the
            # round trip.
            adapter=r.get("adapter") or None,
        )
        (fetchable if source.fetchable else unconfirmed).append(source)
    return fetchable, unconfirmed
