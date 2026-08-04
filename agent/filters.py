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

# The pilot org operates across San Diego AND Imperial Counties — Far South/Border
# North spans both. Never hardcode San Diego alone. This service-area pattern is seed
# configuration; in a multi-tenant build it comes from each org's own settings.
SERVICE_AREA_GEOGRAPHY = re.compile(
    r"(san\s+diego|imperial\s+count|border\s+north|far\s+south|"
    r"southern\s+california|\bcalifornia\b|\bstatewide\b|\bnational\b|"
    r"\bnationwide\b|united\s+states|all\s+50\s+states)",
    re.IGNORECASE,
)

# A page that restricts itself to somewhere the organization is not.
GEOGRAPHY_EXCLUSIVE = re.compile(
    r"((?:only|exclusively|solely|limited\s+to|restricted\s+to|must\s+be\s+located\s+in|"
    r"serving\s+only)\s+(?:organizations?\s+)?(?:in|within|serving)?\s*"
    r"(?!.{0,40}(?:san\s+diego|imperial|california))"
    r"(new\s+york|texas|florida|illinois|massachusetts|washington\s+state|oregon|"
    r"arizona|nevada|colorado|georgia|ohio|michigan|pennsylvania|"
    r"los\s+angeles|orange\s+county|riverside|san\s+bernardino|bay\s+area|"
    r"san\s+francisco|sacramento|fresno|central\s+valley|north\s+county\s+only))",
    re.IGNORECASE,
)

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


def _geography_ok(text: str) -> tuple[bool, str]:
    """Does this page's geography include where the organization works?

    Deliberately permissive: absence of any geographic statement is treated as
    eligible, because rejecting on silence would drop most national funders. Only an
    explicit restriction to somewhere else is a reject.
    """
    exclusive = GEOGRAPHY_EXCLUSIVE.search(text)
    if exclusive and not SERVICE_AREA_GEOGRAPHY.search(exclusive.group(0)):
        return False, exclusive.group(0)[:160]
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

    ok, detail = _geography_ok(haystack)
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
