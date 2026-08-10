"""API adapters for the two indexed sources. (CLAUDE.md Q2/Q3)

Only two, deliberately. Both are complete lists rather than one funder's page, and
both stay up for a structural reason rather than because someone maintains them:

  - California Grants Portal — AB 2252 (2019) requires every CA state agency to post
    its grant opportunities to one public portal. Served as CKAN over data.ca.gov.
  - Grants.gov — every federal discretionary grant, via the public search2 API.

Everything else in `sources.py` stays an HTML crawl. Adding a third API means adding
a function here and one `Source` entry; it does not mean touching `run.py`.

On speed
--------
Both adapters are bounded on purpose, because the weekly run has to finish:
one request for California, and for Grants.gov one search per active program plus
at most `DETAIL_LIMIT` detail lookups. All concurrent. No link-following — the
payload already has what an HTML crawl has to go hunting for.

On honesty
----------
§6 says we never state an amount or a deadline we did not read. An API is not an
exception: field names are read defensively and a value we cannot find stays None
so the record is flagged for a human, rather than being inferred from the shape of
the response. If the payload itself is unrecognizable, the adapter returns an error
and the run records that one source as unhealthy — it does not guess, and it does
not take the rest of the run down with it.

These endpoints are registered at Confidence.LIKELY. The first run that reads real
grant content out of one is what earns it CONFIRMED.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import ProgramCard
from .parse import Evidence, ParsedPage, _parse_date

log = logging.getLogger(__name__)

# --- bounds. These are what keep the weekly run to seconds, not minutes. ------
CA_ROW_LIMIT = 300        # one request; the portal's open set is comfortably under this
GG_ROWS_PER_PROGRAM = 25  # search2 hits per program vocabulary
DETAIL_LIMIT = 12         # Grants.gov detail lookups — the only per-record fanout


@dataclass
class ApiResult:
    """What one adapter returned. `error` set means the source was unhealthy."""

    pages: list[ParsedPage] = field(default_factory=list)
    error: str | None = None
    note: str = ""
    # Free rejects made inside the adapter, folded into the run's reject counters
    # so the Runs tab shows them next to every other zero-cost filter.
    rejected: dict[str, int] = field(default_factory=dict)
    # Things the user needs to READ, as opposed to `note`, which describes what the
    # adapter did. A ticked program that searched nothing belongs here: it is an
    # action they can take, not a statistic, and burying it in a source's detail line
    # means the one person who can fix it never sees it.
    warnings: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _first(record: dict, *names: str) -> str:
    """Read the first field that exists, case-insensitively.

    Schema drift is the failure mode that matters for APIs: a renamed field returns
    200 with a null where the money used to be. Trying the known aliases turns a
    silent wrong answer into either a right one or an honest blank.
    """
    lowered = {k.lower(): v for k, v in record.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, "", []):
            return str(value).strip()
    return ""


_MONEY_TOKEN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion|m|b|k)?", re.I)
_MULTIPLIER = {"k": 1_000, "m": 1_000_000, "million": 1_000_000,
               "b": 1_000_000_000, "billion": 1_000_000_000}


def _structured_amounts(raw: str, label: str) -> list[Evidence]:
    """Read money out of a field whose *name* already says it holds award amounts.

    parse.extract_amounts deliberately refuses any figure whose sentence doesn't
    present it as a per-award number — that guard exists because scraped HTML is full
    of endowment totals and lifetime giving. A field called `EstAmounts` or
    `awardCeiling` carries that meaning in the schema instead of in prose, so running
    the prose heuristic over it just discards a value we already know the meaning of.

    Text with no figures in it at all ("Dependent on number of applications") yields
    nothing, which is correct: §6 says an amount we cannot read stays None.
    """
    out: list[Evidence] = []
    for m in _MONEY_TOKEN.finditer(raw or ""):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        value *= _MULTIPLIER.get((m.group(2) or "").lower(), 1)
        out.append(Evidence(value=int(value), snippet=f"{label}: {raw}"[:300], kind="amount"))
    return out


def _deadline_evidence(raw: str) -> list[Evidence]:
    parsed = _parse_date(raw) if raw else None
    if parsed is None:
        return []
    return [Evidence(value=parsed, snippet=f"deadline: {raw}", kind="deadline")]


# --- California Grants Portal -------------------------------------------------

CA_BASE = "https://data.ca.gov/api/3/action"
CA_PACKAGE = "california-grants-portal"

# The portal's own category taxonomy, mapped onto the org's three programs (§7). This is
# free, structured relevance: without it every run pays Haiku to read dairy, archery
# and dam-safety grants. A record with no category at all is kept, following the same
# permissive convention as the geography filter — absence is not exclusion.
# Keyed by program SLUG rather than by the old three-value enum. The org has seven
# programs and the user can create more from the dashboard, so anything keyed on a fixed
# enum silently ignores every program beyond the original three — which is worse than
# it sounds, because the fallback below then searches ALL categories, making their
# program selection do nothing at all for this source.
CA_CATEGORIES: dict[str, set[str]] = {
    "RULFP": {
        "Education",
        "Employment, Labor & Training",
        "Housing, Community and Economic Development",
    },
    "RESILIENCE": {
        "Health & Human Services",
        "Employment, Labor & Training",
    },
    "ARTS": {
        "Libraries and Arts",
    },
}

# The comment above this dict already named the risk: a program beyond the original
# three contributes nothing here and falls through to "search everything". That was
# meant for a genuinely new org's genuinely new program — it turned out to also be the
# ordinary case for the org THIS was tuned for, the moment they recreated their own
# three cards through "Build it from a link" (the intended way to make one) and got
# different auto-generated slugs (`RISE_ARTS`, not `ARTS`). Confirmed live on a real
# $2 run: none of the three matched, every CA category was searched, and a
# $750K-4.5M heat-infrastructure grant that has nothing to do with any of the org's
# programs survived free filtering into a paid Sonnet call because of it.
#
# `agent/apis.py`'s Grants.gov adapter already solves the equivalent problem correctly
# (`program_vocabularies` below: `card.api_vocabulary()` falls back to the card's own
# keywords when the slug has no tuned default). This is that same fallback for the CA
# portal's fixed category taxonomy — matched against words the card already carries
# (keywords, summary, what it funds), not invented, and only ever WIDENS which
# programs can narrow the search; a program that matches nothing here still falls
# through to the same honest "search everything, and say so" behavior as before.
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "Libraries and Arts": {"art", "arts", "cultural", "culture", "creative"},
    "Health & Human Services": {
        "health", "wellness", "wellbeing", "behavioral", "trauma", "burnout"},
    # "training" alone is too generic to be a signal on its own — RISE Arts' own
    # summary says "cohort-based business development training" for artists, which is
    # nothing to do with workforce/labor programs. Paired terms only.
    "Employment, Labor & Training": {
        "leadership", "workforce", "fellowship", "civic engagement", "employment"},
    "Housing, Community and Economic Development": {
        "housing", "community", "economic"},
    "Education": {"education", "youth", "school"},
}


def _derived_categories(card: ProgramCard) -> set[str]:
    """A best-effort category set for a program whose slug is not one of the three
    tuned above, from the same keywords/summary already on the card — never a category
    outside the portal's own taxonomy already used elsewhere in this file, only a wider
    set of programs able to reach the ones that exist."""
    haystack = " ".join(
        [*card.keywords, card.summary, card.what_it_funds]
    ).lower()
    return {cat for cat, words in _CATEGORY_KEYWORDS.items()
            if any(w in haystack for w in words)}

# Cross-cutting tags that describe who a grant serves, not what it funds. "Disadvantaged
# Communities" sits on urban watershed restoration, sea level rise adaptation and archery
# in schools — real programs, none of them the org's. So it can support a match but never
# make one on its own, or the category filter stops filtering anything.
CA_SUPPORTING = {"Disadvantaged Communities"}

# The org needs grant money, not credit. The portal marks these explicitly, so bond
# programs and revolving loan funds cost nothing to exclude — and they are otherwise
# the loudest rows in the list, because a $5B commercial paper facility outranks
# every real opportunity on award size.
CA_EXCLUDED_TYPES = {"loan"}


async def fetch_ca_grants_portal(fetcher, cfg) -> ApiResult:
    """One CKAN datastore query against the statutory CA grants list.

    Resolves the resource id through package_show rather than hardcoding a UUID —
    CKAN resource ids change whenever a dataset is re-uploaded, and a hardcoded one
    is the single most likely way this adapter silently dies.
    """
    payload, error = await fetcher.fetch_json(
        f"{CA_BASE}/package_show", params={"id": CA_PACKAGE}
    )
    if error:
        return ApiResult(error=f"package_show: {error}")

    resources = (payload or {}).get("result", {}).get("resources", [])
    resource_id = next(
        (r.get("id") for r in resources
         if r.get("datastore_active") and str(r.get("format", "")).upper() == "CSV"),
        None,
    ) or next((r.get("id") for r in resources if r.get("datastore_active")), None)

    if not resource_id:
        return ApiResult(error="no datastore-backed resource in the CA Grants Portal package")

    # Status filtered server-side: the full table is thousands of rows going back
    # years, and only the active ones can be applied for.
    payload, error = await fetcher.fetch_json(
        f"{CA_BASE}/datastore_search",
        params={
            "resource_id": resource_id,
            "limit": CA_ROW_LIMIT,
            "filters": '{"Status":"active"}',
        },
    )
    if error:
        return ApiResult(error=f"datastore_search: {error}")

    records = (payload or {}).get("result", {}).get("records", [])
    if not records:
        return ApiResult(note="portal answered with zero active grants")

    result = ApiResult()

    # Categories for the ticked programs. A program with no mapping (anything beyond
    # the three we tuned) used to contribute nothing here at all — now its own
    # keywords get one try at deriving a category before it falls through to the
    # "search everything" case, so the ordinary act of recreating a card through
    # "Build it from a link" (which mints a new slug every time) doesn't quietly
    # widen every run back to unfiltered. Still never invented: `mapped` and
    # `derived` both only ever narrow using the portal's own fixed taxonomy.
    active = list(cfg.programs_active)
    by_slug = {c.slug: c for c in cfg.programs}
    mapped = [p for p in active if p in CA_CATEGORIES]
    derived: dict[str, set[str]] = {}
    for p in active:
        if p in CA_CATEGORIES:
            continue
        card = by_slug.get(p)
        cats = _derived_categories(card) if card is not None else set()
        if cats:
            derived[p] = cats
    truly_unmapped = [p for p in active if p not in CA_CATEGORIES and p not in derived]

    if not mapped and not derived:
        # Nothing ticked has a category mapping, derived or tuned. Filtering on an
        # empty set would reject every row; filtering on all categories would ignore
        # their selection entirely. Neither is honest, so we don't narrow, and we say
        # so.
        wanted = set().union(*CA_CATEGORIES.values())
        result.warn(
            "No ticked program matches a California funding category "
            f"({', '.join(active) or 'nothing is ticked'}), so every category was "
            "searched. Expect more California results to review than usual."
        )
    else:
        wanted = ({c for p in mapped for c in CA_CATEGORIES[p]}
                 | {c for cats in derived.values() for c in cats})
        covered = mapped + list(derived.keys())
        if truly_unmapped:
            result.warn(
                f"California was searched for {', '.join(covered)} only. "
                f"{', '.join(truly_unmapped)} has no California funding category on "
                "file, so nothing was searched for it there — Grants.gov still "
                "covers it."
            )

    for rec in records:
        title = _first(rec, "Title", "GrantTitle", "title")
        url = _first(rec, "GrantURL", "URL", "ApplicationURL", "url")
        if not title or not url.startswith("http"):
            result.reject("ca_record_missing_title_or_url")  # §6: no URL, no record
            continue

        # The org is a 501(c)(3). A grant open only to public agencies or tribal
        # governments is not an opportunity, and this is a free way to know that.
        eligibility = _first(rec, "ApplicantType", "Eligibility")
        if eligibility and "nonprofit" not in eligibility.lower():
            result.reject("ca_not_open_to_nonprofits")
            continue

        # "Grant; Loan" keeps its grant half, so only a pure loan is excluded.
        types = {t.strip().lower() for t in _first(rec, "Type").split(";") if t.strip()}
        if types and types <= CA_EXCLUDED_TYPES:
            result.reject("ca_loan_not_grant")
            continue

        categories = {c.strip() for c in _first(rec, "Categories").split(";") if c.strip()}
        substantive = categories - CA_SUPPORTING
        if substantive and not (substantive & wanted):
            result.reject("ca_category_off_mission")
            continue

        agency = _first(rec, "AgencyDept", "Agency", "Department") or "State of California"
        description = _first(rec, "Description", "Purpose", "PurposeText")
        amounts_raw = _first(rec, "EstAmounts", "EstimatedAmounts", "AwardAmount")
        funds_raw = _first(rec, "EstAvailFunds", "EstimatedAvailableFunds")
        deadline_raw = _first(rec, "ApplicationDeadline", "CloseDate", "Deadline")
        match_raw = _first(rec, "MatchingFunds")
        geography = _first(rec, "Geography") or "California statewide"

        text = "\n".join(x for x in (
            f"{title} — {agency}",
            description,
            f"Eligible applicants: {eligibility}" if eligibility else "",
            f"Categories: {'; '.join(sorted(categories))}" if categories else "",
            f"Funding type: {_first(rec, 'Type')}" if types else "",
            f"Estimated award amounts: {amounts_raw}" if amounts_raw else "",
            f"Estimated funds available in total: {funds_raw}" if funds_raw else "",
            # Surfaced, not filtered: §11 Q4 (can the org meet a match?) is unanswered,
            # so the run flags it for the user rather than deciding on their behalf.
            f"Matching funds required: {match_raw}" if match_raw else "",
            f"Application deadline: {deadline_raw}" if deadline_raw else "",
            f"Geography: {geography}.",
        ) if x)

        result.pages.append(ParsedPage(
            url=url,
            title=title[:300],
            text=text,
            # Only EstAmounts is a per-award figure. EstAvailFunds is the size of the
            # whole pot, which is not what MIN_AWARD compares against — reading it as
            # an award would inflate every California row.
            amounts=_structured_amounts(amounts_raw, "Estimated award amounts"),
            deadlines=_deadline_evidence(deadline_raw),
            notes=[f"California Grants Portal · {agency}"],
        ))

    # Appended, not assigned: the category-coverage note set before the loop explains
    # WHICH programs were searched for, and overwriting it here would delete the only
    # signal that a ticked program contributed nothing.
    summary = f"{len(result.pages)} of {len(records)} active CA grants are on-mission"
    result.note = f"{summary} · {result.note}" if result.note else summary
    return result


# --- Grants.gov ---------------------------------------------------------------

GG_SEARCH = "https://api.grants.gov/v1/api/search2"
GG_DETAIL = "https://api.grants.gov/v1/api/fetchOpportunity"

# §7: one vocabulary per program, never one search across all of them.
#
# These are the tuned defaults for the three programs we had when this adapter was
# written, keyed by slug. They are DEFAULTS, not the whole story: a program the user
# creates has no entry here and draws its vocabulary from its own card instead
# (ProgramCard.api_vocabulary). Keeping them means their federal results for the three
# priority programs do not change shape because someone edited a keyword list.
GG_SEED_KEYWORDS: dict[str, str] = {
    "RULFP": "community leadership development civic engagement",
    "RESILIENCE": "behavioral health workforce wellness resilience",
    "ARTS": "arts culture creative community",
}


def program_vocabularies(cfg) -> tuple[list[tuple[str, str]], list[str]]:
    """(searchable, skipped) — what to search for, and which cards had nothing to give.

    Returns the ticked programs paired with their search terms, plus the slugs of any
    ticked program whose card is still empty. An empty card is a real state — four of
    the org's seven ship that way on purpose — and the honest response is to search
    nothing for it and say so, not to invent terms from the programme's internal name.
    """
    searchable: list[tuple[str, str]] = []
    skipped: list[str] = []
    for card in cfg.programs:
        terms = card.api_vocabulary(GG_SEED_KEYWORDS.get(card.slug))
        if terms:
            searchable.append((card.slug, terms))
        else:
            skipped.append(card.slug)
    return searchable, skipped


async def fetch_grants_gov(fetcher, cfg) -> ApiResult:
    """Search per active program, then look up award amounts for the top few.

    search2 returns titles and dates but not award ceilings, and the award ceiling is
    the field MIN_AWARD filters on (§7). So a bounded number of detail lookups is the
    difference between a usable federal feed and a pile of amount-not-stated rows.
    """
    searchable, skipped = program_vocabularies(cfg)

    result = ApiResult()
    if skipped:
        # Loud, not silent. They ticked it, so they are expecting results from it, and a
        # program that quietly searched nothing is indistinguishable from one that
        # searched and found nothing — which is the ambiguity this whole project exists
        # to remove.
        result.warn(
            f"Nothing was searched for {', '.join(skipped)} — "
            f"{'those program cards are' if len(skipped) > 1 else 'that program card is'}"
            " still empty. Open it, press Edit, and paste the program's page to fill it in."
        )
        log.warning("Grants.gov: %s", result.warnings[-1])

    if not searchable:
        result.note = "no program had search terms to look for"
        return result

    searches = await asyncio.gather(*(
        fetcher.fetch_json(
            GG_SEARCH,
            method="POST",
            json_body={
                "keyword": terms,
                "oppStatuses": "posted|forecasted",
                "rows": GG_ROWS_PER_PROGRAM,
            },
        )
        for _slug, terms in searchable
    ))

    hits: dict[str, tuple[dict, str]] = {}
    errors: list[str] = []
    for (program, _terms), (payload, error) in zip(searchable, searches):
        if error:
            errors.append(f"{program}: {error}")
            continue
        data = (payload or {}).get("data") or {}
        for hit in data.get("oppHits", []) or []:
            key = str(hit.get("id") or hit.get("number") or "")
            if key and key not in hits:
                hits[key] = (hit, program)

    if not hits:
        # Reuse `result` rather than building a fresh one: it already carries the
        # empty-card warnings, and returning a new ApiResult here would drop exactly
        # the message that explains why there were no hits.
        if errors:
            result.error = "; ".join(errors)
            return result
        result.note = "no federal hits for the active program keywords"
        return result

    # Apply the runway floor BEFORE spending detail lookups. search2 already gives us
    # closeDate for free, and §7 rejects anything inside the floor — so ordering by
    # "soonest" without this spends the entire detail budget on the twelve
    # opportunities guaranteed to be thrown away seconds later.
    floor = date.today() + timedelta(days=cfg.min_deadline_runway_days)
    eligible: list[tuple[dict, str, date]] = []
    for hit, program in hits.values():
        closes = _parse_date(_first(hit, "closeDate", "close_date"))
        if closes is None:
            eligible.append((hit, program, date.max))  # unknown: let a human see it
        elif closes < floor:
            result.reject("deadline_too_soon")
        else:
            eligible.append((hit, program, closes))

    if not eligible:
        result.note = f"all {len(hits)} federal hits close inside the runway floor"
        return result

    # Soonest first among what is actually still applicable — a real deadline is the
    # best reason to spend one of a bounded number of detail lookups.
    ordered = [(h, p) for h, p, _ in sorted(eligible, key=lambda x: x[2])][:DETAIL_LIMIT]

    details = await asyncio.gather(*(
        fetcher.fetch_json(
            GG_DETAIL,
            method="POST",
            json_body={"opportunityId": int(hit["id"])},
        )
        if str(hit.get("id", "")).isdigit() else _no_detail()
        for hit, _ in ordered
    ))

    for (hit, program), (detail_payload, detail_error) in zip(ordered, details):
        number = _first(hit, "number", "oppNumber")
        title = _first(hit, "title", "oppTitle")
        agency = _first(hit, "agency", "agencyName", "agencyCode") or "U.S. federal agency"
        if not title or not number:
            continue

        url = f"https://www.grants.gov/search-results-detail/{hit.get('id')}"

        synopsis: dict = {}
        if not detail_error and isinstance(detail_payload, dict):
            data = detail_payload.get("data") or {}
            synopsis = data.get("synopsis") or data.get("forecast") or {}

        ceiling = _first(synopsis, "awardCeiling", "award_ceiling")
        award_floor = _first(synopsis, "awardFloor", "award_floor")
        close_raw = (_first(synopsis, "responseDate", "closeDate")
                     or _first(hit, "closeDate", "close_date"))
        description = _first(synopsis, "synopsisDesc", "description")
        eligibility = _first(synopsis, "applicantEligibilityDesc", "applicantTypes")

        text = "\n".join(x for x in (
            f"{title} — {agency} (opportunity {number})",
            _strip_tags(description),
            f"Eligibility: {_strip_tags(eligibility)}" if eligibility else "",
            f"Award ceiling: ${ceiling}" if ceiling else "",
            f"Award floor: ${award_floor}" if award_floor else "",
            f"Closes: {close_raw}" if close_raw else "",
            "Geography: national — open to applicants nationwide unless stated otherwise.",
        ) if x)

        notes = [f"Grants.gov · {number}", f"program vocabulary: {program}"]
        if detail_error:
            # Honest: we have the listing but not the money. It will land in the
            # amount-not-stated block rather than being ranked on a guess.
            notes.append(f"award amounts unavailable ({detail_error})")

        result.pages.append(ParsedPage(
            url=url,
            title=title[:300],
            text=text,
            amounts=(_structured_amounts(f"${ceiling}", "Award ceiling") if ceiling else [])
                    + (_structured_amounts(f"${award_floor}", "Award floor") if award_floor else []),
            deadlines=_deadline_evidence(close_raw),
            notes=notes,
        ))

    result.note = f"{len(result.pages)} federal opportunities with runway, from {len(hits)} hits"
    if errors:
        result.note += f" · partial: {'; '.join(errors)}"
    return result


async def _no_detail() -> tuple[None, str]:
    return None, "no numeric opportunity id"


def _strip_tags(text: str, limit: int = 2000) -> str:
    """Grants.gov descriptions arrive with HTML in them. Never send that to a model (§8)."""
    import re

    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"&(nbsp|amp|lt|gt|quot|#39);", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()[:limit]


ADAPTERS = {
    "ca_grants_portal": fetch_ca_grants_portal,
    "grants_gov": fetch_grants_gov,
}
