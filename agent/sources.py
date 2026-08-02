"""The source registry — what the crawler actually visits. (CLAUDE.md §11 Q2)

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

from dataclasses import dataclass, field
from enum import IntEnum

from .models import Program


class Tier(IntEnum):
    WARM = 1          # the 8 funders Mauri confirmed warm (§7)
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

    @property
    def fetchable(self) -> bool:
        return self.url is not None and self.confidence >= Confidence.LIKELY


# --- Tier 1: the eight warm funders (§7, confirmed warm by Mauri) --------------

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


ALL_SOURCES: list[Source] = WARM_SOURCES + INTERMEDIARY_SOURCES + GOVERNMENT_SOURCES


def active_sources(max_tier: Tier = Tier.WARM) -> list[Source]:
    """Sources to crawl this run. Defaults to tier 1 only (§12 Block 1)."""
    return [s for s in ALL_SOURCES if s.tier <= max_tier and s.fetchable]


def unconfirmed_sources(max_tier: Tier = Tier.WARM) -> list[Source]:
    """Registered but unfetchable — the run reports these so they don't go quiet."""
    return [s for s in ALL_SOURCES if s.tier <= max_tier and not s.fetchable]
