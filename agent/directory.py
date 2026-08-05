"""Starter funder lists any org can import. (FUTURE.md §4a)

The 60 sources in `agent/sources.py` are researched work — 58 San Diego grantmakers plus
two national grant databases. They used to be seeded into whichever org happened to sign
in first, which produced the obvious complaint: one account had 52 funders and the
account created five minutes later had none. Nothing about that was a decision; it was an
artefact of `DEFAULT_ORG_ID` existing.

So they are not seeded into anybody. They are a **directory** an org imports from, which
is the honest shape for three reasons:

  1. **It is consistent.** Every org sees the same thing and chooses.
  2. **It is correct outside San Diego.** A Chicago nonprofit should not silently inherit
     58 San Diego foundations, and should still get Grants.gov, which serves everyone.
  3. **It is the feature this is becoming.** The directory page — browse by city, and
     send a stronger model out to find grantmakers not in the list yet — grows from
     exactly this shape rather than replacing it.

The grouping is deliberately coarse. Two national databases that apply to everyone, one
city. When there are five cities the list gets a `city` field and a filter; inventing
that structure now, with one city in it, would be guessing at a shape we can see properly
in a month.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .sources import ALL_SOURCES, Source


@dataclass(frozen=True)
class StarterList:
    key: str
    name: str
    description: str
    # Why it is a predicate rather than a stored list: `sources.py` is the one place a
    # source is written down, and a second copy here would drift the first time somebody
    # adds a funder.
    matches: Callable[[Source], bool]

    @property
    def sources(self) -> list[Source]:
        return [s for s in ALL_SOURCES if self.matches(s)]


STARTER_LISTS: tuple[StarterList, ...] = (
    StarterList(
        key="national",
        name="Federal grants",
        description=(
            "Grants.gov — every federal funding opportunity, searched as a database "
            "rather than crawled. Useful wherever you are."
        ),
        matches=lambda s: s.adapter == "grants_gov",
    ),
    StarterList(
        key="california",
        name="California state grants",
        description=(
            "The California Grants Portal — every state agency's open solicitations. "
            "Useful anywhere in California."
        ),
        matches=lambda s: s.adapter == "ca_grants_portal",
    ),
    StarterList(
        key="san-diego",
        name="San Diego funders",
        description=(
            "Foundations, arts agencies and community funders in San Diego and Imperial "
            "Counties, researched by hand."
        ),
        matches=lambda s: s.adapter is None,
    ),
)


# What a brand-new organization is given before it has chosen anything.
#
# All three, which means a nonprofit outside San Diego starts with 58 funders that are
# not theirs. That is a deliberate trade and it is the lesser problem: an empty funder
# list means the Re-run button does nothing at all, and "the app did nothing" is a worse
# first impression than "some of these are not near me, let me remove them". The Discover
# funders page is where that gets fixed properly — pick your city, drop the ones you did
# not ask for.
DEFAULT_ON_SIGNUP: tuple[str, ...] = ("national", "california", "san-diego")


def get(key: str) -> StarterList | None:
    return next((lst for lst in STARTER_LISTS if lst.key == key), None)


def catalogue() -> list[dict]:
    """What is on offer, for the browser. Counts, never the funders themselves — the
    page needs to know a list is worth importing, not to render it twice."""
    return [
        {"key": lst.key, "name": lst.name, "description": lst.description,
         "count": len(lst.sources)}
        for lst in STARTER_LISTS
    ]
