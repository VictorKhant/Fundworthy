"""Researched California health foundations, outside San Diego. (2026-08-09)

Where these came from
----------------------
The third category researched after family foundations and community foundations,
scoped statewide California on the user's own earlier choice. The brief asked
specifically for "health conversion foundations" — the foundations California law
requires when a nonprofit hospital or health plan converts to for-profit status and has
to give away the resulting assets.

6 candidates passed out of 20 checked, and they are not all the same legal shape — that
distinction is kept visible rather than smoothed over:

  - California Health Care Foundation, Sierra Health Foundation, The Health Trust, and
    Centinela Valley Medical and Community Funds are genuine conversion trusts, each
    tied to a named for-profit sale (Blue Cross → WellPoint 1996; Foundation Health
    Corporation 1984; Good Samaritan Health System → Columbia/HCA 1996; Centinela
    Hospital Medical Center 1999).
  - Sequoia Healthcare District and Peninsula Health Care District are **healthcare
    districts**, not conversion trusts — public agencies funded by property tax and
    lease revenue with the same "give away health-adjacent money to community
    nonprofits" function, the same legal category as Grossmont Healthcare District
    already in `sd_funders.py` (sector="government" there). Included here rather than
    left out, because the function a nonprofit cares about — "can I apply to this for
    money" — is identical; each entry's notes says which kind it is.

The 14 rejected are worth naming because several are the best-known names in California
health philanthropy, explicitly invitation-only on their own current page: The
California Endowment ("Funding opportunities are by invitation only"), The California
Wellness Foundation ("will not accept LOIs or unsolicited grant proposals in 2026"), and
Blue Shield of California Foundation ("we do not accept unsolicited proposals"). Others
were real but currently closed (Desert Healthcare District, Beach Cities Health
District), unreachable for independent verification (El Camino Healthcare District —
403 on every fetch, despite good secondary-source evidence), or defunct (FHP
Foundation, Watts Health Foundation).

Every entry carries a VERBATIM sentence fetched from the funder's own official domain —
not a search snippet or a third-party aggregator, which the same research pass caught
misstating one foundation's eligibility elsewhere this week.
"""

from __future__ import annotations

from .sources import Confidence, Source, Tier

RESEARCHED_SOURCES: list[Source] = [
    Source(
        name="California Health Care Foundation",
        funder="California Health Care Foundation",
        url="https://www.chcf.org/grants/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region="statewide California",
        notes=(
            "\"If you would like to make an unsolicited request, please follow "
            "these instructions.\" · \"While unsolicited requests are accepted by "
            "the foundation, most of our grants are solicited or awarded through a "
            "competitive request for proposals.\" Created 1996 from the conversion "
            "of Blue Cross of California to the for-profit WellPoint (now Anthem/ "
            "Elevance) — the same transaction that also created The California "
            "Endowment, which is invitation-only and NOT in this registry. No "
            "award ceiling or fixed deadline for the unsolicited pathway; no RFP "
            "was posted at check time (\"we do not have a regular cycle for these "
            "requests; we post them as the programmatic need arises\"). CAVEAT: "
            "most CHCF dollars move through solicited RFPs, not this channel — but "
            "the channel is real. GEOGRAPHY: statewide California."
        ),
    ),
    Source(
        name="Sierra Health Foundation",
        funder="Sierra Health Foundation",
        url="https://www.sierrahealth.org/about-us/frequently-asked-questions/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region="26-county Northern/Central California region",
        notes=(
            "\"Will Sierra Health Foundation fund only tax-exempt 501(c)(3) "
            "organizations? No. We also fund public agencies, such as school "
            "districts and state, county and city government. We cannot fund "
            "501(c)(3) nonprofits that are supporting organizations with an "
            "Internal Revenue Code of 509(a)(3).\" Created 1984 from the for-profit "
            "conversion of Foundation Health Corporation. Responsive Grants "
            "Program has distributed ~$8.3M since 2008; no fixed award ceiling "
            "stated. Recurring, not invitation-only, but no open application "
            "deadline was visible at check time — confirm current cycle dates "
            "directly. GEOGRAPHY: 26-county Northern/Central California region."
        ),
    ),
    Source(
        name="The Health Trust",
        funder="The Health Trust",
        url="https://www.thehealthtrust.org/how-to-apply/?tab=community-grants",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region="Santa Clara County and Northern San Benito County",
        notes=(
            "\"Applicants must be public agencies or nonprofit organizations (tax "
            "exempt at the Federal and State level)\" (Health Partnership Grants); "
            "\"Nonprofit organizations must be tax exempt at the Federal and State "
            "level\" (Community Grants). Created 1996 from the sale of Good "
            "Samaritan Health System's hospitals to the for-profit Columbia/HCA. "
            "Community Grants: up to $5,000, rolling (submit 60+ days before "
            "project start). Health Partnership / Health Equity Fund grants: "
            "amount not stated, reviewed quarterly (Sept/Dec/Mar/June). "
            "GEOGRAPHY: Santa Clara County and Northern San Benito County."
        ),
    ),
    Source(
        name="Centinela Valley Medical and Community Funds",
        funder="Centinela Valley Medical and Community Funds",
        url=(
            "https://www.calfund.org/grants/"
            "centinela-valley-medical-community-funds-integration-collaboration-advocacy/"
        ),
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region=("specific South LA County zip codes only (Inglewood, Hawthorne, "
               "Lennox, part of LA, El Segundo, Watts, Compton, Lawndale)"),
        notes=(
            "\"Nonprofit hospitals and nonprofits with health as a focus of their "
            "mission can apply for the funds.\" Created 1999 from the sale of "
            "Centinela Hospital Medical Center (Inglewood) to a for-profit "
            "corporation — a >$50M charitable trust, administered as a component "
            "fund at California Community Foundation (CCF's OWN general "
            "grantmaking is invitation-only and is not this — this is a "
            "separately-governed named fund with its own open pathway). Open on "
            "an ongoing basis via email to a program officer, not a fixed annual "
            "deadline. Awards: nonprofit hospitals $500,000+/2yrs; other "
            "nonprofits $100,000+/2yrs. GEOGRAPHY: narrow — specific South LA "
            "County zip codes only (Inglewood, Hawthorne, Lennox, part of LA, El "
            "Segundo, Watts, Compton, Lawndale), not statewide."
        ),
    ),
    Source(
        name="Sequoia Healthcare District — Caring Community Grants",
        funder="Sequoia Healthcare District",
        url="https://www.seqhd.org/caring-community-grants",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region="southern/central San Mateo County",
        notes=(
            "\"Any 501c3 nonprofit organization or government agency that serves "
            "District residents may apply.\" NOT a for-profit conversion — this is "
            "a healthcare DISTRICT (the same legal category as Grossmont "
            "Healthcare District, already in this registry's San Diego list): "
            "voters rejected a for-profit/Columbia-HCA bid in 1996 and the "
            "district instead leased hospital operations to the nonprofit "
            "Catholic Healthcare West, redirecting property-tax and lease revenue "
            "into community grants. Grants up to $200,000/grant, $400,000/org/ "
            "year, ~$3.75M per cycle. Current specific open-window dates not "
            "confirmed — site shows multi-year cycles through 2026-27. "
            "GEOGRAPHY: southern/central San Mateo County (Redwood City, San "
            "Carlos, Belmont, Atherton, Menlo Park, Portola Valley, Woodside, "
            "part of San Mateo/Foster City)."
        ),
    ),
    Source(
        name="Peninsula Health Care District — Community Grants Program",
        funder="Peninsula Health Care District",
        url="https://www.peninsulahealthcaredistrict.org/faq-guidelines-eligibility",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="health_conversion",
        region="northern San Mateo County",
        notes=(
            "\"Grants are open to 501(c)(3) non-profit organizations or public "
            "agencies serving residents of San Bruno, Millbrae, Burlingame, "
            "Hillsborough, San Mateo, half of Foster City and/or the southeast "
            "corner of South San Francisco.\" Same caveat as Sequoia — a "
            "healthcare DISTRICT, not a for-profit conversion trust; hospital "
            "operations are affiliated with the nonprofit Sutter Health/ "
            "Mills-Peninsula system. Currently open (2027 cycle): LOI due August "
            "26, 2026; full application due October 26, 2026. Awards "
            "$15,000-$70,000. GEOGRAPHY: northern San Mateo County (zip codes "
            "94010, 94011, 94030, 94066, 94401-94404, 94497)."
        ),
    ),
]
