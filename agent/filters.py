"""Deterministic rejects. Zero LLM cost. (CLAUDE.md tier 1)

These run before any model call, so they are free. Everything they kill is a
candidate we never pay to think about.

On nulls
--------
§7 says `REJECT if award_max < MIN_AWARD` but never says what to do when the page
never stated an amount — which is the common case, not the edge case. A filter that
rejects nulls empties the pipeline; one that passes them silently defeats the award
floor, which is the entire product.

So a null amount is not a reject and not a pass: it routes to the
AMOUNT_NOT_STATED section (§6 `Section`), where it is visible but never ranked
against a score it does not have. Same for a null deadline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .config import Config
from .parse import ParsedPage

log = logging.getLogger(__name__)


class Reject(str, Enum):
    """Why a candidate was killed. Counted per run and shown in the Runs tab."""

    BELOW_MIN_AWARD = "below_min_award"
    DEADLINE_TOO_SOON = "deadline_too_soon"
    DEADLINE_PASSED = "deadline_passed"
    GEOGRAPHY = "geography_excludes_service_area"
    RELIGIOUS = "religious_organization"
    POLITICAL = "political_party"
    EXCLUDED_FUNDER = "excluded_funder"
    NOT_AN_OPPORTUNITY = "not_a_funding_opportunity"


class Flag(str, Enum):
    """Not a reject — something a human should look at. (§6 needs_human_check)"""

    AMOUNT_NOT_STATED = "amount_not_stated"
    DEADLINE_NOT_STATED = "deadline_not_stated"
    MATCH_REQUIREMENT = "match_requirement_unknown"  # §11 Q4 unanswered


@dataclass
class FilterResult:
    rejected: bool
    reason: Reject | None = None
    detail: str = ""
    flags: list[Flag] = field(default_factory=list)


# --- §7 rejects ---------------------------------------------------------------

# --- geography ----------------------------------------------------------------
#
# This used to be two hardcoded regexes: one listing San Diego and California as "ours",
# the other listing a dozen other places as "not ours". That made the `org_location`
# setting a lie — a Chicago nonprofit could type "Chicago, Illinois", watch it save, and
# still have every Illinois-only grant rejected for free, in the tier that never explains
# itself. The setting was fully plumbed through the UI and API and changed nothing.
#
# The fix splits the two halves that were tangled together. The vocabulary of *places*
# is universal and belongs in code — the fifty states do not vary by tenant. Which of
# those places is **yours** is configuration, and now genuinely comes from settings.

_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    "georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|"
    "maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|"
    "nevada|new\\s+hampshire|new\\s+jersey|new\\s+mexico|new\\s+york|north\\s+carolina|"
    "north\\s+dakota|ohio|oklahoma|oregon|pennsylvania|rhode\\s+island|south\\s+carolina|"
    "south\\s+dakota|tennessee|texas|utah|vermont|virginia|washington|west\\s+virginia|"
    "wisconsin|wyoming|district\\s+of\\s+columbia"
)

# Metros worth recognising on their own, because a page says "Chicago only" far more
# often than "Illinois only". Each maps to its state so that an org which entered only a
# city still matches a page that restricts itself to that city's state.
_METRO_STATE = {
    "san diego": "california", "los angeles": "california",
    "san francisco": "california", "bay area": "california",
    "sacramento": "california", "fresno": "california",
    "orange county": "california", "riverside": "california",
    "san bernardino": "california", "imperial county": "california",
    "new york city": "new york", "brooklyn": "new york",
    "chicago": "illinois", "houston": "texas", "dallas": "texas",
    "austin": "texas", "san antonio": "texas",
    "philadelphia": "pennsylvania", "phoenix": "arizona",
    "seattle": "washington", "portland": "oregon", "denver": "colorado",
    "boston": "massachusetts", "atlanta": "georgia", "miami": "florida",
    "detroit": "michigan", "minneapolis": "minnesota",
    "new orleans": "louisiana", "baltimore": "maryland",
    "st. louis": "missouri", "kansas city": "missouri",
    "las vegas": "nevada", "cleveland": "ohio", "columbus": "ohio",
}

_PLACES = "|".join([_STATES] + [re.escape(m) for m in sorted(_METRO_STATE, key=len,
                                                             reverse=True)])

# A page that restricts itself to one named place. The place is *captured* rather than
# matched against a fixed "somewhere else" list, so the same pattern serves every org —
# whether it is theirs is decided afterwards, against their own service area.
GEOGRAPHY_RESTRICTION = re.compile(
    r"(?:only|exclusively|solely|limited\s+to|restricted\s+to|must\s+be\s+(?:located|based)\s+in|"
    r"serving\s+only|residents\s+of|open\s+only\s+to)\s+"
    r"(?:organizations?\s+|nonprofits?\s+|applicants?\s+|agencies\s+)?"
    r"(?:that\s+are\s+)?(?:in|within|from|serving|located\s+in|based\s+in)?\s*"
    rf"(?:the\s+)?({_PLACES})\b",
    re.IGNORECASE,
)

# Reach that includes everyone, whoever they are. Never a geographic reject.
UNIVERSAL_GEOGRAPHY = re.compile(
    r"(\bnational\b|\bnationwide\b|united\s+states|all\s+50\s+states|any\s+state|"
    r"across\s+the\s+country)",
    re.IGNORECASE,
)


def service_area_terms(location: str) -> frozenset[str]:
    """The places that count as "ours", from what the org typed in Settings.

    "San Diego County, California" → {"san diego county", "san diego", "california"}.
    A city alone still picks up its state via `_METRO_STATE`, because a page that says
    "Illinois organizations only" is about a Chicago nonprofit even though it never says
    Chicago.

    An empty setting returns an empty set, and an empty set means **no geographic
    rejecting at all** — see `geography_ok`. Guessing a location for an org that has not
    told us one is how the old hardcoded pattern silently discarded another state's
    grants.
    """
    text = (location or "").strip().lower()
    if not text:
        return frozenset()

    terms = {part.strip() for part in re.split(r"[,;/]| and ", text) if part.strip()}
    terms.add(text)
    for metro, state in _METRO_STATE.items():
        if metro in text:
            terms.add(metro)
            terms.add(state)
    for state in re.findall(_STATES, text, re.IGNORECASE):
        terms.add(re.sub(r"\s+", " ", state.lower()))
    # "San Diego County" should also answer to "San Diego".
    for term in list(terms):
        stripped = re.sub(r"\s+(county|counties|city|region|area|metro)$", "", term)
        if stripped and stripped != term:
            terms.add(stripped)
    return frozenset(t for t in terms if len(t) > 2)

RELIGIOUS = re.compile(
    r"\b(church|churches|diocese|diocesan|archdiocese|parish|ministry|ministries|"
    r"evangelical|catholic|christian|jewish\s+federation|synagogue|mosque|islamic\s+relief|"
    r"faith[-\s]based\s+organization|missionary|gospel|bible|congregation)\b",
    re.IGNORECASE,
)

POLITICAL = re.compile(
    r"\b(democratic\s+(?:party|national\s+committee)|republican\s+(?:party|national\s+committee)|"
    r"political\s+action\s+committee|\bpac\b|campaign\s+committee|"
    r"libertarian\s+party|green\s+party|partisan)\b",
    re.IGNORECASE,
)

# REMOVED — there is now one exclusion mechanism, not two.
#
# This used to be `EXCLUDED_FUNDERS = {"county of san diego equity impact grant"}`,
# checked against the funder name. Two things were wrong with it:
#
#   1. It never fired. Not once, across every recorded run. It matched on `funder`,
#      and no source is named "County of San Diego Equity Impact Grant" — the registry
#      has "County of San Diego". It has been sitting here since day one presented as a
#      working §7 hard filter while rejecting nothing.
#   2. Even working, it was a second exclusion list. the user now has a remove list they
#      control; a hardcoded one beside it means "excluded" has two meanings, only one
#      of which they can see or change.
#
# Both now live on the remove list (app/db.py seeds them), which matches on the funder
# name AND the page title — so a single named PROGRAM can be excluded without excluding
# the whole funder, which is what §7 actually asked for: "that is one program, not the
# whole County. Other County solicitations stay eligible."

# NOT in §7. Added after the first crawl surfaced "CALL FOR PANELISTS",
# "Grant Panels", "Recent Grants Search", and "Volunteer Opportunities" as
# candidates. None are money the organization can apply for. Killing them here is free;
# letting them through means paying Haiku to tell us what a regex already knows.
NOT_AN_OPPORTUNITY = re.compile(
    r"(call\s+for\s+panelists?|grant\s+panels?|panelist\s+application|"
    r"volunteer\s+opportunit|past\s+grantees?|grantee\s+database|recent\s+grants\s+search|"
    r"grants?\s+awarded|grantmaking\s+evaluation|annual\s+report|"
    r"board\s+of\s+directors|staff\s+directory|privacy\s+policy|terms\s+of\s+use|"
    r"fiscal\s+sponsorship|job\s+opening|careers?\s+at)",
    re.IGNORECASE,
)

MATCH_REQUIREMENT = re.compile(
    r"(matching?\s+(?:funds?|requirement|contribution|grant)|"
    r"\b1:1\s+match|dollar[-\s]for[-\s]dollar|cost\s+shar(?:e|ing)|"
    r"requires?\s+a\s+match)",
    re.IGNORECASE,
)


def geography_ok(text: str, service_area: frozenset[str]) -> tuple[bool, str]:
    """Does this page's geography include where this org works?

    Deliberately permissive, in two directions. Absence of any geographic statement is
    eligible, because rejecting on silence would drop most national funders. And an org
    that has not told us where it works rejects **nothing** on geography — an empty
    `service_area` disables the filter rather than falling back to somebody else's
    region, which is exactly the bug this replaced.

    Only an explicit restriction to a place that is demonstrably not ours is a reject,
    and a page that also claims national reach is never one.
    """
    if not service_area:
        return True, ""
    if UNIVERSAL_GEOGRAPHY.search(text):
        return True, ""

    for match in GEOGRAPHY_RESTRICTION.finditer(text):
        place = re.sub(r"\s+", " ", match.group(1).lower())
        if any(term in place or place in term for term in service_area):
            continue
        return False, match.group(0)[:160]
    return True, ""


def apply_filters(page: ParsedPage, funder: str, cfg: Config) -> FilterResult:
    """Run every §7 filter. First reject wins; flags accumulate."""
    text = page.text
    haystack = f"{funder}\n{page.title}\n{text[:6000]}"
    flags: list[Flag] = []

    if RELIGIOUS.search(funder):
        return FilterResult(True, Reject.RELIGIOUS, funder)

    if POLITICAL.search(funder):
        return FilterResult(True, Reject.POLITICAL, funder)

    title_and_url = f"{page.title} {page.url}"
    if NOT_AN_OPPORTUNITY.search(title_and_url):
        return FilterResult(True, Reject.NOT_AN_OPPORTUNITY, page.title[:120])

    ok, detail = geography_ok(haystack, service_area_terms(cfg.org_location))
    if not ok:
        return FilterResult(True, Reject.GEOGRAPHY, detail)

    # --- amount. Null is a flag, never a reject (see module docstring).
    #
    # Filter at the LOWEST floor across the ticked programs, not the global one. If
    # RISE Arts accepts $5,000 while everything else needs $10,000, rejecting at
    # $10,000 here would kill Arts opportunities before any program-aware scoring got
    # to look at them. The per-program floor is applied again during scoring, where we
    # know which program a candidate actually matches.
    floor = cfg.effective_min_award
    award_max = page.award_max
    if award_max is None:
        flags.append(Flag.AMOUNT_NOT_STATED)
    elif award_max < floor:
        return FilterResult(
            True, Reject.BELOW_MIN_AWARD, f"${award_max:,} < ${floor:,}",
        )

    # --- deadline. Same rule.
    deadline = page.earliest_deadline
    if deadline is None:
        flags.append(Flag.DEADLINE_NOT_STATED)
    else:
        days = (deadline - date.today()).days
        if days < 0:
            return FilterResult(True, Reject.DEADLINE_PASSED, deadline.isoformat())
        if days < cfg.min_deadline_runway_days:
            return FilterResult(
                True,
                Reject.DEADLINE_TOO_SOON,
                f"{days}d — under the {cfg.min_deadline_runway_days}d floor; "
                "not enough runway for a 10-hour application",
            )

    # §11 Q4 is unanswered — we do not know what match the organization can meet, so we cannot
    # write this filter. Flagging is the honest behavior; guessing is not.
    if MATCH_REQUIREMENT.search(text):
        flags.append(Flag.MATCH_REQUIREMENT)

    return FilterResult(False, flags=flags)


def summarize(results: list[FilterResult]) -> dict[str, int]:
    """Reject counts by reason, for the Runs tab and the evidence package."""
    counts: dict[str, int] = {}
    for r in results:
        if r.rejected and r.reason:
            counts[r.reason.value] = counts.get(r.reason.value, 0) + 1
    return counts
