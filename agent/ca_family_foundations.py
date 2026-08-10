"""Researched California family foundations, outside San Diego. (2026-08-08)

Where these came from
----------------------
The user asked for more predefined starter-list cards beyond federal/state grants and
the San Diego registry, naming family foundations as the first category. Scoped
statewide California, on the user's own choice — see the "geographic scope" question in
the conversation this was written from.

5 candidates passed out of roughly 20 checked. The other 15 are not written down here —
every one of them was a real foundation with a real page, rejected for the same reason
the 36 in sd_funders.py were: no public application pathway. Family foundations skew
invitation-only far more than the community foundations in ca_community_foundations.py
do — James Irvine, Weingart, Stuart, S.H. Cowell, Bernard Osher, Dan Murphy, the Norris
Foundation, Auen, May & Stanley Smith, and several others were all checked and all
explicitly said "invitation only" or "we do not accept unsolicited proposals" on their
own page. The Green Foundation's search snippet read as open-application; its actual
guidelines page said "only institutions that have previously received funding from The
Green Foundation are eligible to apply at this time" — found by fetching the real page
rather than trusting the summary, which is the entire point of this file's rule below.

Every entry carries a VERBATIM sentence from the funder's own page proving it accepts
applications from 501(c)(3) nonprofits and is not invitation-only, fetched and read
before being allowed in here — the same rule sd_funders.py applies, applied here.

A pattern worth naming: none of these are "statewide" in the sense of funding anywhere
in California. Every family foundation found, without exception, is anchored to one
county or metro area (overwhelmingly Los Angeles County — that is where California's
family-foundation philanthropic capital concentrates outside the Bay Area). "Statewide
California" was the right *search scope*; the result is a regional patchwork, not a
single list that covers the state evenly. `ca_community_foundations.py` found the same
shape independently.
"""

from __future__ import annotations

from .sources import Confidence, Source, Tier

RESEARCHED_SOURCES: list[Source] = [
    Source(
        name="The Ahmanson Foundation",
        funder="The Ahmanson Foundation",
        url="https://theahmansonfoundation.org/funding-guidelines/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="family_foundation",
        region="Los Angeles County",
        notes=(
            "The Foundation reviews funding requests from 501(c)(3) public charity "
            "organizations, based in and serving Los Angeles County. · No application "
            "form — a Letter of Inquiry or full proposal goes directly to the Managing "
            "Director. No deadline; accepted throughout the year. Typical award "
            "$10,000-$50,000. Priority is capital expenses; program expenses are "
            "sometimes considered. Requires 3-5 years of operating history and stable "
            "leadership. GEOGRAPHY: Los Angeles County only."
        ),
    ),
    Source(
        name="Ralph M. Parsons Foundation",
        funder="Ralph M. Parsons Foundation",
        url="https://rmpf.org/grantmaking/seeking-our-support/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="family_foundation",
        region="Los Angeles County",
        notes=(
            "The Parsons Foundation accepts Letters of Inquiry (LOIs) via our online "
            "application portal · \"The Parsons Foundation makes grants to public "
            "charities serving Los Angeles County\" · \"Organizations with a "
            "'preliminary ruling' letter from the IRS are eligible.\" Rolling LOIs, no "
            "deadline, ~6-week response. Four program areas: civic/cultural, "
            "education, health, human services. Median award $50,000; grants rarely "
            "exceed 10% of an organization's budget. LIMIT: only one request per "
            "organization per year. GEOGRAPHY: Los Angeles County only."
        ),
    ),
    Source(
        name="Sidney Stern Memorial Trust",
        funder="Sidney Stern Memorial Trust",
        url="https://sidneysternmemorialtrust.org/guidelines",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="family_foundation",
        region="",
        notes=(
            "\"A recipient organization must be exempt from income taxation under "
            "Federal law as a 501(c)3.\" · \"The Board accepts, reviews and votes on "
            "grant applications throughout the year.\" · \"There are no deadlines for "
            "submission. Requests for grants are considered within eighteen months of "
            "receipt.\" Priorities: education, youth summer camps, socio-economic "
            "equity, food security, legal justice, medical research/care, arts and "
            "arts education, scientific research. Award range not stated. GEOGRAPHY: "
            "\"all funds must be used within the United States\" — no California-only "
            "restriction found, but the trust itself is California-based."
        ),
    ),
    Source(
        name="Zellerbach Family Foundation — Community Arts",
        funder="Zellerbach Family Foundation",
        url="https://communityarts.zff.org/guidelines-and-eligibility/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="family_foundation",
        region="Alameda, Contra Costa, or San Francisco County",
        notes=(
            "\"The Community Arts program of the Zellerbach Family Foundation has an "
            "open application process; all other grantmaking is done by invitation.\" "
            "— this is the ONE open program at Zellerbach; nothing else there is "
            "worth adding. · \"Hold a 501c3 nonprofit organization status or are "
            "fiscally sponsored individual artists, organizations, collectives, or "
            "groups.\" Awards $5,000 / $10,000 / $15,000, ~$1M/year total, quarterly "
            "cycles. Applicant budget must be under $2 million. GEOGRAPHY: Alameda, "
            "Contra Costa, or San Francisco County only."
        ),
    ),
    Source(
        name="Rose Hills Foundation",
        funder="Rose Hills Foundation",
        url="https://rosehillsfoundation.org/funding-guidelines/",
        tier=Tier.WARM,
        confidence=Confidence.CONFIRMED,
        sector="family_foundation",
        region="Los Angeles County",
        notes=(
            "\"The Rose Hills Foundation supports qualified tax-exempt charitable "
            "organizations\" for the benefit of Southern California, \"with a current "
            "emphasis on organizations based in and serving Los Angeles County.\" "
            "CAVEATS THAT WILL BITE: first-time applicants must have an annual "
            "operating budget of at least $1.5 million for L.A. County operations to "
            "even be eligible, and first-time grantees cannot receive multi-year "
            "funding. All applicants — new or returning — take a screening "
            "eligibility quiz before an application is offered; review then runs "
            "6-8 months. Excludes charter schools, hospitals, public universities, "
            "filmmaking projects, and orgs serving only San Bernardino or the San "
            "Fernando Valley. GEOGRAPHY: Los Angeles County emphasis."
        ),
    ),
]
