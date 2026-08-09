"""Researched California community foundations, outside San Diego. (2026-08-08)

Where these came from
----------------------
The user asked for more predefined starter-list cards beyond federal/state grants and
the San Diego registry. Community foundations were the second category researched,
scoped statewide California on the user's own choice.

12 candidates passed out of 20 checked. The 8 rejected are worth naming because the
reasons are the actual finding, not just noise: California Community Foundation (Los
Angeles) and Marin Community Foundation both explicitly do not accept unsolicited
proposals on their own pages; Sacramento Region, Napa Valley and Ventura County
Community Foundations either 404'd on their specific grant pages or had every named
fund marked closed at fetch time; Kern Community Foundation's live programs were either
a narrow fit or explicitly "not accepting applications right now"; North Valley
Community Foundation's specific funds were closed pending a 2026 reopening; Central
Valley Community Foundation's own page states it is "refining" its open call and plans
to relaunch it in 2026.

Every entry carries a VERBATIM sentence from the funder's own page proving it accepts
applications from 501(c)(3) nonprofits (posted funds, not cold unsolicited proposals in
Orange County's case — see its note), fetched and read before being allowed in here —
the same rule sd_funders.py applies, applied here.

A pattern worth naming, found independently of the same finding in
ca_family_foundations.py: every one of these is anchored to a specific county or small
cluster of counties. There is no single foundation that covers California statewide;
"statewide California" as a search scope correctly produces a regional patchwork, not
one list. Each entry's notes says exactly which county or counties it serves.
"""

from __future__ import annotations

from .sources import Confidence, Source, Tier

RESEARCHED_SOURCES: list[Source] = [
    Source(
        name="Silicon Valley Community Foundation",
        funder="Silicon Valley Community Foundation",
        url="https://www.svcf.org/nonprofits/grants-2",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"SVCF awards grants through an open Request for Proposals (RFP) "
            "process.\" · \"Organizations with a 501(c)(3) designation, those that "
            "have a fiscal sponsor with a 501(c)(3) designation, public agencies, "
            "collaborations of nonprofit and public agencies, or other entities that "
            "have a designated charitable purpose will be considered.\" One open RFP "
            "round per year (2025 cycle: opened Mar 3, closed Mar 31). Community "
            "Action Grants exclude orgs with budgets over $3M; primarily general "
            "operating support. GEOGRAPHY: San Mateo and/or Santa Clara counties "
            "(orgs elsewhere may apply if they demonstrably serve these counties)."
        ),
    ),
    Source(
        name="The San Francisco Foundation",
        funder="The San Francisco Foundation",
        url="https://sff.org/what-we-do/funding/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"All 501(c)(3) nonprofit organizations based in the five Bay Area "
            "counties we serve can apply to the following funding opportunities.\" "
            "Multiple named funds (e.g. FAITHS Community Partner Grants, Rapid "
            "Response Fund for Movement Building); award ranges and deadlines vary "
            "by fund and are posted per-program. GEOGRAPHY: Alameda, Contra Costa, "
            "Marin, San Francisco, and San Mateo counties."
        ),
    ),
    Source(
        name="Humboldt Area Foundation",
        funder="Humboldt Area Foundation",
        url="https://hafoundation.org/requesting-support/grantseekers-portal/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Non-profit organizations, public benefit organizations (including "
            "churches, educational organizations/schools, hospitals, government "
            "units, tribal governments, etc.), groups working with a qualified "
            "fiscal sponsor, and other organizations and groups working on "
            "charitable projects are eligible to apply for grants.\" Applies via an "
            "online Grants Portal; specific award amounts and deadlines vary by fund "
            "and live in the portal rather than this overview page. Operates jointly "
            "as Wild Rivers Community Foundation. GEOGRAPHY: Humboldt, Del Norte, "
            "and Trinity counties (CA), plus Curry County (OR)."
        ),
    ),
    Source(
        name="Community Foundation Sonoma County",
        funder="Community Foundation Sonoma County",
        url="https://www.sonomacf.org/nonprofits/grant-faq/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Our competitive grants are open to incorporated, charitable 501(c)(3) "
            "organizations serving Sonoma County.\" Multiple named programs (Arts "
            "Education, BIPOC Leadership Fund, Basic Human Needs, Sonoma County "
            "Resilience Fund, etc.); award ranges and deadlines vary by program and "
            "are posted per-fund. GEOGRAPHY: Sonoma County."
        ),
    ),
    Source(
        name="Stanislaus Community Foundation",
        funder="Stanislaus Community Foundation",
        url="https://www.stanislauscf.org/grant-cycle",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"The Stanislaus Community Foundation's (SCF) Resilient Stanislaus Fund "
            "will provide support to 501(c)(3) nonprofit organizations serving "
            "Stanislaus County.\" Priority given to requests under $5,000; "
            "$5,000-$10,000 is highly competitive; awards over $10,000 are rare. "
            "Reviewed on a rolling basis as funds allow. GEOGRAPHY: Stanislaus "
            "County."
        ),
    ),
    Source(
        name="Community Foundation for Monterey County",
        funder="Community Foundation for Monterey County",
        url="https://cfmco.org/nonprofits/grants/community-impact/guidelines",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Impact grants are open to 501(c)3* nonprofit organizations and "
            "public agencies serving Monterey County residents.\" Impact Grants "
            "$20,001-$50,000 (2026 deadline March 20); Small Grants $10,000-$20,000 "
            "(rolling, Feb/Jun/Oct deadlines). ~$2.6M awarded annually across all "
            "CFMC programs. Fiscal sponsorship accepted for unincorporated "
            "applicants. GEOGRAPHY: Monterey County."
        ),
    ),
    Source(
        name="Santa Barbara Foundation",
        funder="Santa Barbara Foundation",
        url="https://sbfoundation.org/nonprofits/community-grant-guidelines/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Organizations must be certified as tax exempt under Section 501(c)(3) "
            "of the Internal Revenue Code or use a fiscal sponsor with 501(c)(3) tax "
            "status.\" Community Grant Program: up to $60,000 total over two years "
            "($30,000/yr). 2026 deadlines by track: Behavioral Health & Health Care "
            "Mar 3; Food Apr 28; Shelter & Safety Aug 11. Separate Small Capacity "
            "Building Grant, max $6,000, four cycles/year. An org may be awarded in "
            "only one program area. GEOGRAPHY: Santa Barbara County."
        ),
    ),
    Source(
        name="Community Foundation San Luis Obispo County",
        funder="Community Foundation San Luis Obispo County",
        url="https://www.cfsloco.org/nonprofits-2/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"In good standing with the Internal Revenue Service as a 501(c)(3) "
            "and/or 509(a)(1), or able to provide a current contract outlining a "
            "fiscal sponsorship relationship with a 501(c)(3).\" Multiple programs, "
            "e.g. General Community Grants (up to $20,000 one-year / $40,000 "
            "two-year, $140,000 available per priority area); Growing Together "
            "LGBTQ+ Fund (up to $10,000); Women's Legacy Fund (up to $20,000/ "
            "$40,000). Applicant must be based in or have operated in the county "
            "for 12+ months; several specific cycles were closed at check time but "
            "the program structure recurs annually. GEOGRAPHY: San Luis Obispo "
            "County."
        ),
    ),
    Source(
        name="Inland Empire Community Foundation",
        funder="Inland Empire Community Foundation",
        url="https://www.iegives.org/students/grant-faq/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Nonprofit, public benefit organizations with evidence of tax-exempt "
            "status under Section 501(c)(3) of the Internal Revenue Code and not "
            "classified as a private foundation.\" · \"The Inland Empire Community "
            "Foundation offers various grant programs which are posted on our "
            "website here.\" Flagship Community Impact Fund: up to $20,000, "
            "unrestricted/general operating; 2025 cycle awarded $850K across 45 "
            "orgs from 132 applications. Applicant operating budget generally under "
            "$2M for that fund. GEOGRAPHY: Riverside and San Bernardino counties."
        ),
    ),
    Source(
        name="Orange County Community Foundation",
        funder="Orange County Community Foundation",
        url="https://www.oc-cf.org/nonprofits/faqs/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Other grant applications are considered from 501(c)(3) nonprofit "
            "organizations whose work is aligned with our mission and priority "
            "impact areas.\" CAVEAT: OCCF's own FAQ also says \"We do not accept "
            "unsolicited proposals\" — nonprofits apply to specific POSTED open "
            "funds via the Available Grants page rather than submitting cold "
            "proposals. Confirmed live example: Jane Deming Fund (Orange County "
            "music/arts charities), 2026 cycle open, deadline April 17, real public "
            "application form. GEOGRAPHY: Orange County."
        ),
    ),
    Source(
        name="Pasadena Community Foundation",
        funder="Pasadena Community Foundation",
        url="https://pasadenacf.org/for-nonprofits/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Be a tax-exempt organization under Section 501(c)(3) or 170(c)(1) or "
            "(2)(b).\" Oversees ~11 grant programs annually (Animal Welfare, Arts & "
            "Culture, Capital, Education, Senior, Vista Nova, etc.), ~$2.5M/year to "
            "100+ nonprofits. Award ranges vary by program (e.g. Arts & Culture "
            "$5,000-$25,000; Senior $5,000-$20,000). Requires 2+ years of operating "
            "history; one PCF grant per calendar year. GEOGRAPHY: Pasadena Unified "
            "School District boundaries (Pasadena, Altadena, Sierra Madre)."
        ),
    ),
    Source(
        name="Long Beach Community Foundation",
        funder="Long Beach Community Foundation",
        url="https://longbeachcf.org/grants/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="community_foundation",
        notes=(
            "\"Grants are made to US-based, 501(C)(3) nonprofits, educational "
            "institutions, and government entities serving Long Beach who are in "
            "good standing with the IRS.\" Community Impact Grant: $25,000-$100,000; "
            "2026 cycle — LOI due April 27, full proposal due June 12. Strategic "
            "focus areas set annually by the Board (2026 cycle references youth "
            "engagement tied to the 2028 Olympics). GEOGRAPHY: City of Long Beach."
        ),
    ),
]
