"""990 filing lookup, via ProPublica's Nonprofit Explorer. (§11 Q5 — the COO's 4th criterion)

What this gives you, and what it does not
-----------------------------------------
the user asked for the 990 so they can see "who they have given to and how much". Only half
of that is reachable at a cost this project can justify, and the honest thing is to say
which half.

  ✅ REACHABLE — ProPublica's free API: the funder's EIN, its most recent filing year,
     total revenue and total expenses, and a direct link to the filing. That answers
     "is this an organisation that moves money at the organization's scale, or a $40k family fund
     whose page happens to read well?" — which is a real screening question.

  ❌ NOT REACHABLE cheaply — the grantee list (Schedule I / 990-PF Part XV). It is not
     in any API. The only source is the IRS bulk XML, and we checked: the old
     per-EIN S3 objects are gone (index_2023.json now 404s, the bucket lists nothing),
     leaving only year-sized ZIPs — 123 MB for ONE PART of one year, several parts per
     year. Downloading and indexing that to answer 44 lookups fails the stakeholder's
     own stated bar: cost-optimised, sustainable, no fragile dependencies.

So the link is the bridge. Every result carries a one-click "view their 990" that lands
on the filing, where the grantee list is a scroll away for the cases where they want it.
If the organization later gets Candid/Foundation Directory access (§11 Q2, still unanswered), that
is the clean way to close the gap — it is a paid API that serves grantee data directly.

Why this is not scored
----------------------
Their instruction was "also look at 990 form", and the weight split they chose puts the
100 points on program fit, award size and feasibility. So this is context, not a score:
it is shown next to the result, and the scoring prompt is told to use it to judge
PROGRAM FIT better rather than as a criterion of its own.

Cost and cadence
----------------
Funder financials change annually, not weekly. Lookups are therefore cached on the
FUNDER row, not recomputed per run — 44 requests once, then effectively never again.
ProPublica is free and has run this service for years, which is about as low as
deprecation risk gets for a third-party API.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

SEARCH_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json"
ORG_URL = "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"
PUBLIC_PAGE = "https://projects.propublica.org/nonprofits/organizations/{ein}"

TIMEOUT = 20.0

# Registry names carry the PROGRAM, the legal name does not. "The Kresge Foundation
# (Health Program)", "Doris Duke Foundation — Performing Arts" and "Bank of America
# Charitable Foundation — Grant Funding for Nonprofits" all fail a literal search; the
# organisation before the separator is what the IRS indexes.
_TRIM = re.compile(r"\s+[—–|]\s*.*$|\s+-\s+.*$")
_NOISE = re.compile(r"\([^)]*\)")

# Bodies that do not file a Form 990 at all, so a "no match" is the right answer rather
# than a lookup failure. Counting these as misses would make the feature look broken
# when it is working exactly as it should.
_NOT_A_501C3 = re.compile(
    r"\b(city of|county of|state of|department of|district attorney|"
    r"port of|sandag|board of state|federal|national endowment|"
    r"healthcare district|band of|tribe|nation)\b",
    re.IGNORECASE,
)


def files_a_990(name: str) -> bool:
    """False for government agencies and tribal governments — they file nothing."""
    return not _NOT_A_501C3.search(name or "")


def search_name(name: str) -> str:
    """The funder's likely legal name, for a registry that indexes legal names.

    ProPublica's search is a literal token match, which two real cases break:
      - "W.K. Kellogg Foundation" returns ZERO results; "W K Kellogg Foundation"
        returns the right one. Periods inside initials have to become spaces.
      - "The Parker Foundation" returns 19 unrelated Parkers; "Parker Foundation"
        returns the actual one. A leading article has to go.
    """
    cleaned = _NOISE.sub("", name or "")
    cleaned = _TRIM.sub("", cleaned)
    cleaned = cleaned.replace(".", " ")
    cleaned = re.sub(r"^\s*the\s+", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -—–|:")


async def lookup(name: str, fetcher=None) -> dict | None:
    """Return 990 facts for a funder, or None if we could not confidently identify it.

    Deliberately conservative about identity. Matching the wrong EIN would attach one
    organisation's finances to another's name on the user's screen, which is exactly the
    class of confident-but-wrong output §6 exists to prevent — so a fuzzy match is no
    match.
    """
    import httpx

    if not files_a_990(name):
        log.debug("990: %r is a government or tribal body — no filing exists", name)
        return None

    query = search_name(name)
    if len(query) < 4:
        return None

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            found = await client.get(SEARCH_URL, params={"q": query})
            if found.status_code != 200:
                return None
            orgs = (found.json() or {}).get("organizations") or []
            org = _best_match(query, orgs)
            if org is None:
                log.debug("990: no confident match for %r", query)
                return None

            ein = str(org.get("ein") or "").strip()
            if not ein:
                return None

            detail = await client.get(ORG_URL.format(ein=ein))
            filings = ((detail.json() or {}).get("filings_with_data") or []
                       if detail.status_code == 200 else [])
    except Exception as exc:  # noqa: BLE001 — a lookup failing must never fail a run
        log.debug("990 lookup failed for %r: %s", name, exc)
        return None

    latest = filings[0] if filings else {}
    return {
        "ein": ein,
        "matched_name": org.get("name"),
        "form_990_url": PUBLIC_PAGE.format(ein=ein),
        "form_990_year": latest.get("tax_prd_yr"),
        "form_990_total_revenue": _int(latest.get("totrevenue")),
        "form_990_total_expenses": _int(latest.get("totfuncexpns")),
        "form_990_available": bool(filings),
    }


def _best_match(query: str, orgs: list[dict]) -> dict | None:
    """An exact name match or nothing.

    ProPublica returns 202 results for "San Diego Foundation", most of them unrelated
    organisations that merely share a word. Taking result [0] would attach one charity's
    finances to another charity's name on the user's screen — a confident wrong answer,
    which is the specific failure §6 exists to prevent. So: exact token match, and when
    that is ambiguous, nothing.
    """
    want = _key(query)
    exact = [o for o in orgs if _key(o.get("name", "")) == want]

    if len(exact) == 1:
        return exact[0]

    if len(exact) > 1:
        # Real case: "Parker Foundation" is an exact match in both CA and PA. This
        # registry is San Diego-focused, so California is the better prior — but only
        # when it breaks the tie outright. Two Californian matches stay ambiguous.
        californian = [o for o in exact if str(o.get("state", "")).upper() == "CA"]
        if len(californian) == 1:
            return californian[0]
        log.debug("990: %r matched %d organisations — too ambiguous to use",
                  query, len(exact))
        return None

    return None


def _key(name: str) -> str:
    stripped = re.sub(r"\b(the|inc|incorporated|a|of)\b", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", "", stripped)


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summary_line(data: dict | None) -> str:
    """One line for the scoring prompt. Empty when we know nothing."""
    if not data or not data.get("form_990_year"):
        return ""
    parts = [f"IRS 990 for {data['form_990_year']}"]
    if data.get("form_990_total_expenses"):
        parts.append(f"total expenses ${data['form_990_total_expenses']:,}")
    if data.get("form_990_total_revenue"):
        parts.append(f"total revenue ${data['form_990_total_revenue']:,}")
    return " · ".join(parts)
