"""API adapters for the two indexed sources. (CLAUDE.md §11 Q2/Q3)

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

from .models import Program
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

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


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

# The portal's own category taxonomy, mapped onto RISE's three programs (§7). This is
# free, structured relevance: without it every run pays Haiku to read dairy, archery
# and dam-safety grants. A record with no category at all is kept, following the same
# permissive convention as the geography filter — absence is not exclusion.
CA_CATEGORIES: dict[Program, set[str]] = {
    Program.RULFP: {
        "Education",
        "Employment, Labor & Training",
        "Housing, Community and Economic Development",
    },
    Program.RESILIENCE: {
        "Health & Human Services",
        "Employment, Labor & Training",
    },
    Program.ARTS: {
        "Libraries and Arts",
    },
}

# Cross-cutting tags that describe who a grant serves, not what it funds. "Disadvantaged
# Communities" sits on urban watershed restoration, sea level rise adaptation and archery
# in schools — real programs, none of them RISE's. So it can support a match but never
# make one on its own, or the category filter stops filtering anything.
CA_SUPPORTING = {"Disadvantaged Communities"}

# RISE needs grant money, not credit. The portal marks these explicitly, so bond
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
    wanted = {c for p in CA_CATEGORIES if p in cfg.programs_active
              for c in CA_CATEGORIES[p]} or set().union(*CA_CATEGORIES.values())

    for rec in records:
        title = _first(rec, "Title", "GrantTitle", "title")
        url = _first(rec, "GrantURL", "URL", "ApplicationURL", "url")
        if not title or not url.startswith("http"):
            result.reject("ca_record_missing_title_or_url")  # §6: no URL, no record
            continue

        # RISE is a 501(c)(3). A grant open only to public agencies or tribal
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
            # Surfaced, not filtered: §11 Q4 (can RISE meet a match?) is unanswered,
            # so the run flags it for Mauri rather than deciding on her behalf.
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

    result.note = f"{len(result.pages)} of {len(records)} active CA grants are on-mission"
    return result


# --- Grants.gov ---------------------------------------------------------------

GG_SEARCH = "https://api.grants.gov/v1/api/search2"
GG_DETAIL = "https://api.grants.gov/v1/api/fetchOpportunity"

# §7: three programs, three vocabularies. Never one search across all three.
GG_KEYWORDS: dict[Program, str] = {
    Program.RULFP: "community leadership development civic engagement",
    Program.RESILIENCE: "behavioral health workforce wellness resilience",
    Program.ARTS: "arts culture creative community",
}


async def fetch_grants_gov(fetcher, cfg) -> ApiResult:
    """Search per active program, then look up award amounts for the top few.

    search2 returns titles and dates but not award ceilings, and the award ceiling is
    the field MIN_AWARD filters on (§7). So a bounded number of detail lookups is the
    difference between a usable federal feed and a pile of amount-not-stated rows.
    """
    programs = [p for p in GG_KEYWORDS if p in cfg.programs_active] or list(GG_KEYWORDS)

    searches = await asyncio.gather(*(
        fetcher.fetch_json(
            GG_SEARCH,
            method="POST",
            json_body={
                "keyword": GG_KEYWORDS[p],
                "oppStatuses": "posted|forecasted",
                "rows": GG_ROWS_PER_PROGRAM,
            },
        )
        for p in programs
    ))

    hits: dict[str, tuple[dict, Program]] = {}
    errors: list[str] = []
    for program, (payload, error) in zip(programs, searches):
        if error:
            errors.append(f"{program.value}: {error}")
            continue
        data = (payload or {}).get("data") or {}
        for hit in data.get("oppHits", []) or []:
            key = str(hit.get("id") or hit.get("number") or "")
            if key and key not in hits:
                hits[key] = (hit, program)

    if not hits:
        if errors:
            return ApiResult(error="; ".join(errors))
        return ApiResult(note="no federal hits for the active program keywords")

    result = ApiResult()

    # Apply the runway floor BEFORE spending detail lookups. search2 already gives us
    # closeDate for free, and §7 rejects anything inside the floor — so ordering by
    # "soonest" without this spends the entire detail budget on the twelve
    # opportunities guaranteed to be thrown away seconds later.
    floor = date.today() + timedelta(days=cfg.min_deadline_runway_days)
    eligible: list[tuple[dict, Program, date]] = []
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

        notes = [f"Grants.gov · {number}", f"program vocabulary: {program.value}"]
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
