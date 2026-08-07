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
    # Retired — kept so historical run rows that recorded it still read back. Nothing
    # produces it any more; see the note above RELIGIOUS.
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

# --- geography: deliberately not a filter --------------------------------------
#
# There used to be a geographic reject here, and it is gone rather than fixed.
#
# It began as two hardcoded regexes naming San Diego as "ours" and a dozen other places
# as "not ours", which made the `org_location` setting a lie: a Chicago nonprofit could
# type "Chicago, Illinois", watch it save, and still have every Illinois-only grant
# discarded for free — in this tier, which never explains itself to anyone. Reading the
# setting fixed the lie but kept the mistake, which is that a text filter is the wrong
# instrument for this question at all.
#
# Where an org can apply is decided by **which funders it chose to search**, not by
# pattern-matching prose on a page we already decided to fetch. An org that picks the
# San Diego funder list is already only seeing San Diego funders; re-deriving that from
# the words on each page adds nothing and gets it wrong in both directions — rejecting a
# national program that happens to name a state, and passing a regional one that never
# names its region.
#
# The replacement is a funder directory the org picks cities from (FUTURE.md §4a). Until
# it exists, an unwanted funder is one un-tick on the remove list — a lever the user can
# see and change, which a silent regex was not.

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
                f"not enough runway for a {cfg.max_effort_hours}-hour application",
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
