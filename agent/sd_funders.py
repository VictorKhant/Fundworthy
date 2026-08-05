"""Researched San Diego / California funders open to nonprofit applications.

Where these came from
---------------------
the org told us the partner list was the wrong target: they already receive money from
those funders consistently and do not want to reapply. That left the crawl with almost
nothing — the two indexed databases produced 37 candidates and zero survivors in the
last scored run — so this registry is the replacement.

88 candidates were proposed across six independent lanes (community foundations, health
equity, arts, leadership/equity, corporate local, government local), then EVERY one had
its URL fetched and read before it was allowed in here. 52 passed; 36 were rejected,
overwhelmingly because they are invitation-only or publish no application pathway at
all — "Price Philanthropies Foundation is not accepting unsolicited requests" and so on.
Deduplicating by domain left the 44 below.

Every entry carries a VERBATIM sentence from the funder's own page showing it funds
nonprofit organisations. That is the same rule §6 applies to award amounts, applied to
the registry itself: guessing a funder's URL was falsified once already (evidence E2),
and an entry nobody read is a guess wearing a URL's clothes.

What is NOT verified
--------------------
Award amounts. Most of these pages do not publish one, and the researchers were told
not to record a range they could not quote. Deadlines likewise. The pipeline will find
those where they exist and say "not stated" where they do not.

Some entries carry a live-cycle caveat in their notes — a page whose "apply now" badge
was stale at the time of reading, or whose posted deadline had already passed. Those are
kept because the URL is right and the cycle recurs; the crawl re-reads them weekly.
"""

from __future__ import annotations

from .models import Program
from .sources import Confidence, Source, Tier

RESEARCHED_SOURCES: list[Source] = [
    Source(
        name="National Endowment for the Arts \u2014 Grants for Arts Projects",
        funder="National Endowment for the Arts \u2014 Grants for Arts Projects",
        url="https://www.arts.gov/grants/grants-for-arts-projects",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="arts_agency",
        notes=(
            "Nonprofit, tax-exempt 501(c)(3), U.S. organizations \u00b7 Confirmed on "
            "the funder's own page. Award bands: Challenge America flat $10,000; "
            "standard GAP $10,000-$100,000; Local Arts Agency subgranting "
            "$30,000-$150,000. Two cycles listed: Part 1 Feb 12 2026 / Part 2 Feb "
            "25 2026, and Part 1 Jul 9 2026 / Part 2 Jul 21 2026 \u2014 BOTH have "
            "already passed as of today (Aug 2 2026), so the next actionable "
            "cycle is Feb 2027. Two live blockers for the org: (1) '1:1 Cost share "
            "required. Sources may include both cash and in-kind' \u2014 this is "
            "CLAUDE.md \u00a711 Q4, still unanswered by the user; in-kind counting makes "
            "it more plausible than a cash match. (2) 'Applicant organizations "
            "must have completed at least 5 years of a"
        ),
    ),
    Source(
        name="Imperial Valley Community Foundation",
        funder="Imperial Valley Community Foundation",
        url="https://www.ivcommunityfoundation.org/current-rfps/",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "We are currently accepting applications for the Ocotillo Wind "
            "Imperial Valley Fund grant program. \u00b7 PROPOSED URL WAS WRONG. "
            "/funds-programs/ loads (200 with a browser UA) but is a directory of "
            "donor funds plus lists of PAST grantees and scholarships \u2014 not an "
            "application page; its only relevant line is 'When one of these funds "
            "is taking applications, we will announce it, and give information on "
            "how to apply.' The applications live at /current-rfps/, which is the "
            "URL recorded here. That page currently carries one RFP (Ocotillo "
            "Wind Imperial Valley Fund) with deadline '7:59pm (Pacific) on "
            "Thursday, April 30, 2026' \u2014 already past at time of check, so the "
            "page is stale. Applications route out t"
        ),
    ),
    Source(
        name="Imperial Valley Wellness Foundation",
        funder="Imperial Valley Wellness Foundation",
        url="https://www.ivwf.org/grants/",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "We invite 501(c)(3) nonprofits to apply for funding in one of the "
            "following three areas: 1) Family and Community Wellbeing, 2) "
            "Community Voice and Strength, and 3) Nonprofit Capacity Building. \u00b7 "
            "AWARD SIZE IS THE PROBLEM: 'one-year, Health and Wellness grants "
            "ranging from $1,000 \u2013 $10,000 per recipient.' Its Oct 16 2025 news "
            "post announced $102,500 across 18 nonprofits (~$5.7K average). "
            "Expect the MIN_AWARD hard filter to reject everything this source "
            "produces; keep it only if the user wants Imperial County coverage "
            "regardless. CYCLE STATUS: the live page is still headed '2025 "
            "Imperial Valley HEALTH AND WELLNESS Grant' and says 'Applications "
            "have closed.' No 2026 cycle is announced on either"
        ),
    ),
    Source(
        name="Jewish Community Foundation of San Diego \u2014 Competitive Application Platform (CAP)",
        funder="Jewish Community Foundation of San Diego \u2014 Competitive Application Platform (CAP)",
        url="https://jcfsandiego.org/organizations/competitive-application-platform-cap/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "Current 501(c)3 organizations located in and serving San Diego "
            "County may apply for program funding by filling out the application "
            "at the link below. \u00b7 Rotating multi-funder portal \u2014 a good weekly "
            "crawl target because cycles open and close on the same URL. State at "
            "fetch (Aug 2 2026): only ONE cycle marked 'Application Open' \u2014 San "
            "Marcos Community Foundation, restricted to '501(c)3 organizations "
            "located in and/or serving residents of San Marcos' (North County, "
            "outside the org's Far South/Border North footprint). County-wide "
            "Cushman Foundation cycle shows 'Grant closed' but the page says the "
            "Cushman board 'reviews and awards grants on a quarterly basis "
            "throughout the year', so it should reopen"
        ),
    ),
    Source(
        name="San Diego Pride",
        funder="San Diego Pride",
        url="https://sdpride.org/grants/",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "a 501(c)(3) organization or have a 501(c)(3) fiscal sponsor \u00b7 Real, "
            "open, competitive community grants program with a published cycle. "
            "Eligibility: 'LGBTQIA+-serving organizations, groups, and/or "
            "coalitions that are providing direct services or programming in line "
            "with Pride's mission'. AWARD FLOOR WARNING \u2014 grants are "
            "'$1,000-$5,000' out of a '$70,000' pool. That is almost certainly "
            "below whatever MIN_AWARD the user sets and will not justify a 10-hour "
            "application, so expect the deterministic filter to reject it every "
            "week (cheap, zero LLM cost, but also zero yield). Recommend the "
            "parent agent flag this one for the user's call rather than auto- "
            "crawling it. Cycle is CLOSED right now: 'Typically,"
        ),
    ),
    Source(
        name="The Country Friends",
        funder="The Country Friends",
        url="https://countryfriends.org/funding/",
        tier=Tier.WARM,
        programs=[],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "You may be eligible for funding from The Country Friends\u00ae, if your "
            "agency offers preventative programs, encourages self-improvement, "
            "works with special needs individuals, and/or job training. \u00b7 Genuine "
            "open competitive cycle for organizations (not individuals), with a "
            "published calendar. Geography is confirmed and favorable: 'Funds "
            "will be used solely within San Diego County'; they exclude 'Agencies "
            "that do not have an office in San Diego'. TIMING \u2014 the page states "
            "'The 2028 funding cycle will open for applications February 1, 2027' "
            "with current-cycle decisions announced January 2027, so there is no "
            "window open as of Aug 2026; a weekly crawl will find nothing until "
            "Feb 2027. PROGRAM FIT IS"
        ),
    ),
    Source(
        name="The Human Dignity Foundation (San Diego)",
        funder="The Human Dignity Foundation (San Diego)",
        url="https://thehdf.org/grants/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        sector="community",
        notes=(
            "We invite organizations serving LGBTQIA+ communities to apply for "
            "grants that advance dignity, equity, and belonging in San Diego. \u00b7 "
            "Genuinely open, twice-yearly cycles with live 'Apply for a Grant' "
            "links \u2014 good crawl target. HARD ELIGIBILITY RESTRICTION: every cycle "
            "funds 'organizations serving the LGBTQIA+ community' (or, for the "
            "collaborative, 'organizations serving people living with HIV and "
            "AIDS'). the org only qualifies with a program that genuinely serves "
            "those residents \u2014 this is the user's judgment call, not an agent one. "
            "STALE STATUS BADGE: Summer Grant Cycle is badged 'Open' with "
            "'Applications are accepted through July 19th', a date already past "
            "at fetch time; treat that deadline as u"
        ),
    ),
    Source(
        name="Bank of America Charitable Foundation \u2014 Grant Funding for Nonprofits",
        funder="Bank of America Charitable Foundation \u2014 Grant Funding for Nonprofits",
        url="https://about.bankofamerica.com/en/making-an-impact/grant-funding-for-nonprofits-sponsorship-programs",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "tax-exempt under section 501(c)(3) of the Internal Revenue Code, not "
            "classified as a private foundation and not operating through a "
            "fiscal agent or sponsor \u00b7 RENAME THIS ENTRY. The proposed name 'Arts "
            "& Culture' is wrong and would mis-seed the crawl. I read the "
            "eligibility page (https://about.bankofamerica.com/en/making-an- "
            "impact/eligibility-criteria) and the RFP FAQ "
            "(https://about.bankofamerica.com/en/making-an-impact/charitable- "
            "foundation-grant-faq): the four current priorities are basic needs, "
            "income creation, stable housing, and empowering communities. Arts is "
            "NOT a priority. The FAQ states arts organizations are 'welcome to "
            "apply if your organization can demonstrate an alignment to ou"
        ),
    ),
    Source(
        name="Cox Charities West Region \u2014 Community Grants",
        funder="Cox Charities West Region \u2014 Community Grants",
        url="https://www.coxcharitieswest.org/community-grants",
        tier=Tier.WARM,
        programs=[],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "Cox Charities Community Grants are awarded to nonprofits in our West "
            "Region service areas. \u00b7 Page is real but thin: it names the eight "
            "West Region markets (San Diego included) and states the 2025 cycle "
            "is CLOSED ('Our 2025 Community Grant cycle has now closed. "
            "Applicants can look forward to a response to their application by "
            "September 2025.'). NOT VERIFIED on the funder's own page: award "
            "amounts (the candidate's $10k-$25k band appears only on third-party "
            "aggregators), 501(c)(3) language, and the 'Local Market Needs' focus "
            "bucket. The proposed San Diego sub-page /community-grants-sd 404s; "
            "the Phoenix sibling page /community-grants-phx does load and lists "
            "focus areas Conservation & Sustainab"
        ),
    ),
    Source(
        name="Hunter Industries Community Impact Grants",
        funder="Hunter Industries Community Impact Grants",
        url="https://hunter.global/community-impact-grants",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "We support this commitment by sharing corporate profits annually "
            "with qualifying nonprofit organizations. While we accept "
            "applications from all nonprofit organizations, we focus our efforts "
            "in San Diego County, CA; Clermont, FL; and Tijuana, MX. \u00b7 URL "
            "CORRECTED. The proposed URL https://hunter.global/hunter-industries- "
            "charitable-giving redirects (HTTP 200 after redirect) to "
            "https://hunter.global/community-impact-grants -- register the "
            "destination. APPLICATION CURRENTLY CLOSED, verbatim: 'Currently, our "
            "grant application is closed.' The page also still says 'All "
            "applications will be reviewed beginning in February 2023', which is "
            "stale copy left on a page whose footer reads 'Copyright 2026'"
        ),
    ),
    Source(
        name="Kaiser Permanente Southern California - Community Health Grants",
        funder="Kaiser Permanente Southern California - Community Health Grants",
        url="https://community.kp.org/grants-and-volunteering/funding-opportunities",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "Kaiser Permanente's grants and event sponsorships are offered to "
            "nonprofit organizations, government entities, and academic "
            "institutions based on current funding priorities and the location of "
            "their programs and services. \u00b7 INCLUDE BUT HEAVILY QUALIFIED -- the "
            "main grant channel is CLOSED to unsolicited applicants. Verbatim "
            "from the live page: 'NOTE: In 2019 the regional grants program will "
            "transition to an invitation only grant process. Unsolicited Letters "
            "of Intent (LOIs) or proposals will no longer be accepted.' and "
            "'Beginning in 2019, grants will be made to pre-identified "
            "organizations through a competitive Request for Proposal (RFP) "
            "process.' The candidate description's claim of an op"
        ),
    ),
    Source(
        name="Mission Federal Credit Union \u2014 'Community is Everything' Fund",
        funder="Mission Federal Credit Union \u2014 'Community is Everything' Fund",
        url="https://www.missionfed.com/news-stories/mission-fed-invests-500000-into-san-diego-community-through-community-is-everything-fund/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "Eligible nonprofit organizations interested in receiving 2025 "
            "funding must serve the San Diego region and demonstrate how the "
            "funding may help address community needs or inequities. \u00b7 URL "
            "CORRECTED. The proposed /npo/ page loads but is banking services for "
            "nonprofits \u2014 deposit products, financial wellness workshops, and the "
            "'Mission for Nonprofits' $50 account-opening donation. It has no "
            "grant content and must not be registered. I also checked /community/ "
            "and /community/mission-for-nonprofits/: neither carries grant "
            "application details either. The only page on the domain with real "
            "grant terms is this news post, which confirms verbatim 'grants "
            "ranging up to $25,000 per organization' and 'Ap"
        ),
    ),
    Source(
        name="San Diego Gas & Electric (SDG&E) Corporate Giving",
        funder="San Diego Gas & Electric (SDG&E) Corporate Giving",
        url="https://www.sdge.com/more-information/community/funding-guidelines",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "SDG&E supports and partners with hundreds of community-based "
            "nonprofit organizations in San Diego and south Orange Counties \u00b7 "
            "CONFIRMED, and the candidate's arts warning is CORRECT and verified "
            "verbatim. Exclusion list on the page includes, verbatim: 'Programs "
            "primarily focused on the arts and humanities' -- so DO NOT tag ARTS "
            "for this funder; pitch the leadership/civic/workforce pipeline only. "
            "SECOND GEOGRAPHY WARNING the candidate description missed: the "
            "exclusion list also bars, verbatim, 'Programs whose beneficiaries "
            "are outside of San Diego County and south Orange County'. IMPERIAL "
            "COUNTY BENEFICIARIES ARE EXCLUDED. Since the org's Far South/Border "
            "North work spans San Diego AND Imperial"
        ),
    ),
    Source(
        name="Sony Electronics \u2014 CREATE ACTION",
        funder="Sony Electronics \u2014 CREATE ACTION",
        url="https://alphauniverse.com/createaction/",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "non-profit organizations in the United States having a 501(c)(3) "
            "status with the IRS, other than educational institutions \u00b7 IMPORTANT "
            "\u2014 the evidence quote is from the Official Rules at "
            "alphauniverse.com/legal/create-action-2024-program/, not the landing "
            "page. The landing page itself is thin (mission statement plus 37 "
            "recipient tiles, no eligibility, no amounts, no deadline); the "
            "/createaction/faq/ path 404s. Keep the landing page as the watch URL "
            "but score from the Official Rules. Verified verbatim from the rules: "
            "'$50,000 USD to use for the Grant winner's Action Plan' plus "
            "'$50,000 USD worth of Sony Electronics products'; open to 'the 50 "
            "U.S. and D.C. (excl territories)'; educational inst"
        ),
    ),
    Source(
        name="Sundt Foundation",
        funder="Sundt Foundation",
        url="https://www.sundt.com/foundation/",
        tier=Tier.WARM,
        programs=[],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "All recognized 501(c)(3) organizations that meet the Foundation's "
            "giving guidelines may apply \u00b7 Cleanest eligibility statement of any "
            "page I read, and the quarterly deadlines are confirmed verbatim: "
            "'The deadlines to apply for grants are March 15, June 15, September "
            "15 and December 15.' But two honest flags. (1) PROGRAM FIT IS POOR: "
            "the page's stated focus is 'youth development, military & veterans, "
            "hunger & nutrition, and other basic needs' \u2014 none of the org's three "
            "programs are named, which is why programs is empty. (2) AWARD SIZE "
            "UNVERIFIED AND PROBABLY BELOW FLOOR: the page states only 'Each "
            "year, the foundation awards over $2 million in grants' \u2014 the "
            "$2,500-$25,000 range and ~$5,000 aver"
        ),
    ),
    Source(
        name="Sycuan Band of the Kumeyaay Nation / Sycuan Casino Resort - Community Development",
        funder="Sycuan Band of the Kumeyaay Nation / Sycuan Casino Resort - Community Development",
        url="https://www.sycuan.com/donation-guidelines/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "We pride ourselves on being a dedicated partner to numerous local "
            "charities ranging from social and health services to the arts and "
            "the environment. \u00b7 EVIDENCE PROVENANCE -- READ THIS. The quoted "
            "sentence is NOT on the donation-guidelines page. I read that page "
            "twice and it contains only submission mechanics: required documents, "
            "mailing address, and 'Sycuan's review process can typically take "
            "between 3-4 weeks and you will receive a written response at the "
            "conclusion of the review period.' It uses the neutral word "
            "'organization' throughout and never states nonprofit eligibility, "
            "funding priorities, geography, or award amounts. The evidence "
            "sentence above is from the sibling page https://ww"
        ),
    ),
    Source(
        name="U.S. Bank Foundation \u2014 Community Possible (Play)",
        funder="U.S. Bank Foundation \u2014 Community Possible (Play)",
        url="https://www.usbank.com/about-us-bank/community/community-possible-grant-program/play-grants.html",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "Organizations must have tax-exempt status under IRS section "
            "501(c)(3) and certify that they maintain a non-discrimination policy "
            "\u00b7 Verified against the funder's own 2026 guidelines PDF "
            "(https://www.usbank.com/content/dam/usbank/en/documents/pdfs/about- "
            "us-bank/community-possible-grant-guidelines-2026.pdf), which I "
            "extracted and read \u2014 cite that PDF as source_url, it is far more "
            "substantive than the HTML landing page. California IS confirmed in "
            "Appendix A verbatim: 'U.S. Bank provides funding in the following "
            "locations: Arizona Arkansas California Colorado...'. IMPORTANT "
            "NUANCE the proposed entry got half right: the PDF says 'U.S. Bank "
            "Foundation accepts applications by invitation only. Howe"
        ),
    ),
    Source(
        name="Viejas Band of Kumeyaay Indians - Community Support",
        funder="Viejas Band of Kumeyaay Indians - Community Support",
        url="https://viejasbandofkumeyaay.org/viejas-community/community-support/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="corporate",
        notes=(
            "If we accept your request and you represent a non-profit "
            "organization, we will contact you for a completed W-9 and a copy of "
            "the IRS tax determination letter confirming the non-profit status. \u00b7 "
            "CONFIRMED. Funding preferences verified verbatim: 'We give "
            "preference to requests that meet proven and researched community "
            "needs in one of these five areas of focus: Diversity, Environment, "
            "Youth and Seniors, Education, Cultural Preservation' -- plus 'While "
            "we give preferences to requests that align with these five areas of "
            "focus, we also consider requests outside of these areas.' Diversity "
            "and Cultural Preservation support RULFP and ARTS pitches "
            "respectively, as the candidate claimed. Process verb"
        ),
    ),
    Source(
        name="Doris Duke Foundation \u2014 Performing Arts",
        funder="Doris Duke Foundation \u2014 Performing Arts",
        url="https://www.dorisduke.org/grants/letter-of-inquiry",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Only letters of inquiry submitted by U.S. nonprofit organizations "
            "will be reviewed, as the foundation cannot award grants directly to "
            "individuals. \u00b7 Cleanest nonprofit-only eligibility statement in the "
            "batch, and it is a genuinely open intake channel \u2014 but read the "
            "funder's own warning, verbatim: 'While very few grants result from "
            "unsolicited letters of inquiry, foundation staff do review "
            "unsolicited letters from nonprofit organizations.' Practical "
            "consequences for the registry: this page carries NO award amount, NO "
            "award range, and NO deadline. Under the CLAUDE.md accuracy rules "
            "that means every record parsed from it must have "
            "award_min/award_max/deadline null and needs_human_check = True"
        ),
    ),
    Source(
        name="Hearst Foundations",
        funder="Hearst Foundations",
        url="https://www.hearstfdn.org/health/funding-priorities",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "not registered as 501(c)(3) organizations. An IRS determination "
            "letter is required to receive funding \u00b7 BLOCKING ELIGIBILITY CHECK "
            "BEFORE THIS IS USABLE: Hearst does not fund organizations 'operating "
            "with audited expenses less than $2 million.' That is CLAUDE.md open "
            "question #7 \u2014 if the org's audited expenses are under $2M, this funder "
            "is a guaranteed reject every week and should be pulled. The "
            "candidate write-up said $1M; the page says $2M. Confirmed good news: "
            "national (only exclusion is 'based outside of the United States'), "
            "rolling with no deadlines ('The Hearst Foundations have a year- "
            "round, rolling application; there are no deadlines'), and 'Minimum "
            "grant size is $100,000' \u2014 well above"
        ),
    ),
    Source(
        name="Nathan Cummings Foundation",
        funder="Nathan Cummings Foundation",
        url="https://nathancummings.org/become-a-partner/",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Nathan Cummings Foundation (NCF) is now welcoming proposals for "
            "partnerships via our Letters of Inquiry (LOI) portals year-round. \u00b7 "
            "CONFIRMED OPEN, ROLLING. Page is a genuine prospective-grantee "
            "intake pathway: LOI portal open year-round, 'Applications will be "
            "reviewed on a rolling basis as the portal will remain open for REEJ- "
            "related LOIs year-round.' Award size stated verbatim on page: 'Most "
            "of our grants range from about $50,000 - $250,000' (PRIs "
            "$250k-$750k) -- comfortably above any plausible the org award floor. "
            "Decision timeline: 'NCF staff anticipates notifying applicants to "
            "learn more about their submissions within 12 weeks of submission.' "
            "NOT ELIGIBLE / excluded, verbatim: '501(c)(4)"
        ),
    ),
    Source(
        name="Robert Wood Johnson Foundation",
        funder="Robert Wood Johnson Foundation",
        url="https://www.rwjf.org/en/grants/active-funding-opportunities.html",
        tier=Tier.WARM,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "In making a grant to you, the Foundation needs to determine whether "
            "you are tax-exempt under Section 501(c)(3) of the Internal Revenue "
            "Code \u00b7 Live, dated, cycling listing page \u2014 this is a good weekly "
            "crawl target. As of this check it says 'We are not accepting grant "
            "proposals at this time' but lists two opportunities with imminent "
            "release dates: RWJF Health Policy Fellows (releases Aug 4, 2026) and "
            "Connecting Champions for Diversity, Equity, Inclusion, and Belonging "
            "in the Health Professions (releases Aug 6, 2026). Neither of those "
            "two is a strong the org fit \u2014 both are health-professions focused and "
            "the Fellows program is for individuals \u2014 so expect the crawler to "
            "reject the current contents"
        ),
    ),
    Source(
        name="Rosenberg Foundation",
        funder="Rosenberg Foundation",
        url="https://rosenbergfound.org/how-to-apply",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Nonprofit organizations that are tax-exempt under Section 501(c)(3) "
            "\u00b7 URL CORRECTED. The proposed /grantmaking/ URL resolves but is only "
            "a four-tile program overview with no eligibility or process \u2014 "
            "crawling it would yield nothing. The real grantseeker page is "
            "https://rosenbergfound.org/how-to-apply (verified 200; /apply, "
            "/grantmaking-process/ and /faq all 404). Use the corrected URL. This "
            "is the strongest genuine open door in the whole batch: 'Letters of "
            "Inquiry are accepted on an on-going basis,' and while the page is "
            "candid that 'we do accept unsolicited inquiries, our limited grants "
            "budget means that we can fund only a few of them,' the door is open "
            "with no deadline. Eligibility covers"
        ),
    ),
    Source(
        name="S. Mark Taper Foundation",
        funder="S. Mark Taper Foundation",
        url="https://www.smtfoundation.org/guidelines.html",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "An applicant must be certified as a tax-exempt organization under "
            "Section 501(c)(3) of the Internal Revenue Code. \u00b7 IMPORTANT "
            "CORRECTION \u2014 the candidate write-up is wrong on geography. Taper "
            "does NOT fund eight counties and does NOT include San Diego County. "
            "Verbatim: 'The S. Mark Taper Foundation will consider a Letter of "
            "Inquiry from a non-profit organization that provides services in any "
            "of the following five Southern California counties:' \u2014 Los Angeles, "
            "Imperial, Riverside, San Bernardino, Ventura. San Diego County "
            "appears nowhere on the page. Imperial County IS included, so the org is "
            "eligible only for work delivered in Imperial County (Far South / "
            "Border North). Flag this to the user befor"
        ),
    ),
    Source(
        name="The Andy Warhol Foundation for the Visual Arts",
        funder="The Andy Warhol Foundation for the Visual Arts",
        url="https://warholfoundation.org/grants/application-guidelines/",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Grant requests from US-based 501c3 organizations are reviewed twice "
            "a year. \u00b7 Cleanest entry on this list: a real, open, dated "
            "application page with unambiguous nonprofit-only eligibility. Also "
            "verbatim: 'A copy of the organization's 501(c)3 ruling from the IRS; "
            "we do not accept proposals through fiscal sponsors' \u2014 the org must "
            "apply under its own EIN, no fiscal sponsorship. Deadlines are fixed "
            "and recurring: 'The postmark/email timestamp deadlines for proposals "
            "are March 1 and September 1 every year. Applicants are notified of "
            "the Board's funding decisions July 1st and January 1st "
            "respectively.' The Sept 1, 2026 deadline is roughly a month out \u2014 "
            "clears the 14-day filter, but the 10-hour appl"
        ),
    ),
    Source(
        name="The Kresge Foundation (Health Program)",
        funder="The Kresge Foundation (Health Program)",
        url="https://kresge.org/grants-social-investments/current-funding-opportunities/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Annually, Kresge makes more than 400 grants to nonprofits. \u00b7 "
            "Legitimate open-call listing page and a reasonable weekly crawl "
            "target, but set expectations: as of this check it says 'We currently "
            "do not have any funding opportunities open,' and the parent page "
            "https://kresge.org/grants-social-investments/ says 'Most often, we "
            "invite applicants. Occasionally, program teams issue an open call "
            "for LOIs within a focus area.' So this is a low-yield watch page, "
            "not a reliable pipeline \u2014 most weeks it will produce zero rows, "
            "which is fine under the cap-not-quota design. When open, Kresge "
            "awards 'single-year and multiyear grants that fund general "
            "operating, projects and planning activities' across s"
        ),
    ),
    Source(
        name="The NAMM Foundation \u2014 Music Program Grants",
        funder="The NAMM Foundation \u2014 Music Program Grants",
        url="https://www.nammfoundation.org/sites/default/files/2026GlobalGrantmakingGuidelines.pdf",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "Must have 501(c)(3) status or international equivalency. \u00b7 CRAWLER "
            "WARNING: the proposed URL "
            "https://www.nammfoundation.org/projects/program-grant-track returns "
            "HTTP 503 to every automated fetcher I tried, including curl with a "
            "full browser user-agent \u2014 nammfoundation.org appears to bot-block "
            "the whole HTML site (503/403 across five different paths). The only "
            "machine-readable source that actually loaded is the 2026 Global "
            "Grantmaking Guidelines PDF linked above, which is where the evidence "
            "quote comes from. Register the PDF URL, not the HTML page, or the "
            "source will fail silently every week. Verified from the PDF: award "
            "range verbatim 'Grants from The NAMM Foundation can range between "
            "$5,0"
        ),
    ),
    Source(
        name="The Parker Foundation",
        funder="The Parker Foundation",
        url="https://theparkerfoundation.org/grant-making/",
        tier=Tier.WARM,
        programs=[Program.ARTS, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "The Parker Foundation is committed to partnerships with a wide "
            "variety of social, arts, community, and educational organizations in "
            "San Diego County. \u00b7 Strongest of the ten \u2014 a genuinely open, "
            "unsolicited application with a real published process. The substance "
            "is one level down at /grant-making/grant-seekers/application- "
            "process-online/ (verified 200); note that /grant-making/grant- "
            "seekers/ itself 404s, so do not crawl that path. That sub-page "
            "confirms all the gating facts verbatim: 'The Foundation supports "
            "nonprofit organizations in their efforts to improve life for all San "
            "Diegans'; requires 'verification that the charitable organization "
            "requesting the grant is at present a charitable or"
        ),
    ),
    Source(
        name="W.K. Kellogg Foundation",
        funder="W.K. Kellogg Foundation",
        url="https://www.wkkf.org/grantseekers/",
        tier=Tier.WARM,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="foundation",
        notes=(
            "We are honored to support an array of organizations creating a world "
            "where children, families and communities can thrive. \u00b7 CONFIRMED "
            "OPEN, NO DEADLINES. Verbatim: 'Our application process is always "
            "open. In general, we don't have specific grantmaking cycles or "
            "deadlines.' Process, verbatim from page: register in the Fluxx "
            "grants management system, submit a letter of inquiry (LOI), then a "
            "formal proposal if invited; WKKF commits to 'Making 80% of our final "
            "funding decisions within 60 business days of receiving a formal "
            "online proposal.' Exclusions, verbatim: 'We are unable to make "
            "grants for individuals, capital investments, political parties or "
            "candidates.' Geography, verbatim: 'Across th"
        ),
    ),
    Source(
        name="California Board of State and Community Corrections (BSCC) \u2014 California Violence Intervention and Prevention (CalVIP)",
        funder="California Board of State and Community Corrections (BSCC) \u2014 California Violence Intervention and Prevention (CalVIP)",
        url="https://www.bscc.ca.gov/s_cpgpcalvipgrant/",
        tier=Tier.GOVERNMENT,
        programs=[],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "Eligible applicants now include: Cities disproportionately impacted "
            "by violence; Community-based organizations (CBOs) serving these "
            "cities; Counties with cities facing significant gun violence issues; "
            "Tribal governments experiencing violence \u00b7 URL CORRECTED \u2014 THE "
            "PROPOSED URL IS WRONG. https://www.bscc.ca.gov/calvip/ 301-redirects "
            "to https://www.bscc.ca.gov/calvip-evaluation-resources/, which is a "
            "grantee-support page of RDA Consulting training videos on data "
            "collection and quarterly progress reports. It contains no funding "
            "information whatsoever and would be a dead source. The real program "
            "page is https://www.bscc.ca.gov/s_cpgpcalvipgrant/ (reached via "
            "/s_cpgpcalvip/), and that is the URL"
        ),
    ),
    Source(
        name="California Department of Health Care Access and Information (HCAI) \u2014 CBO Behavioral Health Workforce Grant Program",
        funder="California Department of Health Care Access and Information (HCAI) \u2014 CBO Behavioral Health Workforce Grant Program",
        url="https://hcai.ca.gov/workforce/financial-assistance/grants/bhp/",
        tier=Tier.GOVERNMENT,
        programs=[Program.RESILIENCE],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "The Community-Based Organization (CBO) Behavioral Health Workforce "
            "Grant Program will support CBOs to recruit and retain behavioral "
            "health personnel, and provide loan repayments, scholarships, and "
            "stipends to paid and unpaid CBO behavioral health staff. \u00b7 INCLUDE "
            "BUT DOWNGRADE HARD \u2014 THE SPECIFIC PROGRAM NAMED IN THIS CANDIDATE IS "
            "DEAD. The CBO Behavioral Health Workforce Grant Program appears on "
            "the page under the heading 'Previously Funded Programs', immediately "
            "beneath the verbatim line: 'The programs below do not have future "
            "planned funding at this time.' Its only live assets are the "
            "2022-2023 grant guide, five addenda, an FAQ and the 2023 CBO "
            "Awardees list. The candidate's '$117.7M is"
        ),
    ),
    Source(
        name="California Department of Social Services \u2014 Stop the Hate Program",
        funder="California Department of Social Services \u2014 Stop the Hate Program",
        url="https://cdss.ca.gov/inforesources/cdss-programs/civil-rights/care-funding",
        tier=Tier.GOVERNMENT,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "the Stop the Hate (STH) Program that awards funding to qualified "
            "nonprofit organizations to provide support and services to victims "
            "and survivors of hate incidents and hate crimes and their families \u00b7 "
            "BEST CANDIDATE ON THIS LIST, and the candidate's thematic read holds "
            "up against the actual page text. Statewide California, so San Diego "
            "and Imperial are in scope. Nonprofit eligibility is stated in the "
            "authorizing sentence quoted above (Cal. Gov. Code sec. 8260). The "
            "page carries a live 'Stop the Hate Request for Application and "
            "application packet' link, which is why I scored it as a grants page "
            "rather than a grantee list, even though a large share of the page is "
            "award announcements. ELIGIBL"
        ),
    ),
    Source(
        name="City of San Diego \u2014 Community Projects, Programs and Services (CPPS) Funding Program",
        funder="City of San Diego \u2014 Community Projects, Programs and Services (CPPS) Funding Program",
        url="https://www.sandiego.gov/citycouncil/cpps",
        tier=Tier.GOVERNMENT,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "City Council Community Projects, Programs and Services (CPPS) funds "
            "are awarded at the discretion of each City Councilmember to "
            "nonprofit organizations, public agencies, and City Departments for "
            "community, social, environmental, cultural, and recreational needs "
            "that serve lawful public purposes. \u00b7 ACT NOW \u2014 the FY27 window is "
            "open and closes in five days. Verbatim: 'The Fiscal Year 2027 "
            "application is open from July 7-August 7,2026.' and 'Applications "
            "will only be accepted through the Seamless Docs platform and are due "
            "at midnight on August 7. Late submission will not be accepted.' "
            "Today is Aug 2, 2026. Note this falls inside CLAUDE.md's 'REJECT if "
            "deadline is within 14 days' hard filter,"
        ),
    ),
    Source(
        name="County of San Diego \u2014 Community Enhancement Program",
        funder="County of San Diego \u2014 Community Enhancement Program",
        url="https://www.sandiegocounty.gov/content/sdc/cao/edga/grants/community-enhancement.html",
        tier=Tier.GOVERNMENT,
        programs=[Program.ARTS, Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "The Community Enhancement Program provides grant funds to nonprofit "
            "organizations and public agencies for programs and services that "
            "promote: Tourism, Job creation and economic development, Quality of "
            "life, Cultural activities \u00b7 CRAWLER BLOCKER: this host returns HTTP "
            "403 to the standard fetcher and to plain httpx. It only returned 200 "
            "with a browser User-Agent (curl + Mozilla/5.0 UA, 62KB of real "
            "content). fetch.py must send a browser UA for sandiegocounty.gov or "
            "this source will silently fail every week. Eligibility read verbatim "
            "from the page: 'Non-profit organizations must have Tax Exempt/Non- "
            "profit status with the IRS and be registered and in good standing "
            "with the California Attorney"
        ),
    ),
    Source(
        name="Grossmont Healthcare District",
        funder="Grossmont Healthcare District",
        url="https://grossmonthealthcare-ca2.specialdistrict.org/grants-sponsorships",
        tier=Tier.GOVERNMENT,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "Requests for grant funding for nonprofit 501(c)3 organizations, "
            "fiscally sponsored entities, and public agencies \u00b7 STRONGEST "
            "CANDIDATE IN THIS BATCH. Open right now \u2014 the application portal is "
            "accessible 'August 1 through August 31', which as of Aug 2 2026 "
            "means a live window; awards announced starting November 2026. Award "
            "range is '$50,000 to $300,000' against a board-budgeted '$3.25 "
            "million' for FY 2026-27, comfortably above any plausible MIN_AWARD "
            "and easily worth 10 hours. GEOGRAPHIC CAVEAT \u2014 THE ONE THING TO "
            "CHECK BEFORE APPLYING: funding supports 'projects that operate "
            "within District boundaries or serve District residents', i.e. East "
            "County San Diego (~520,000 residents, La Mesa HQ)"
        ),
    ),
    Source(
        name="Imperial County \u2014 Community Benefit Grant Program (Public Benefit Program)",
        funder="Imperial County \u2014 Community Benefit Grant Program (Public Benefit Program)",
        url="https://imperialcounty.org/cbgrant/",
        tier=Tier.GOVERNMENT,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "Public Benefit Grant Program funds are only available for non-profit "
            "entities. \u00b7 Loads cleanly with no bot blocking. Genuinely valuable "
            "as one of the very few grant sources headquartered in Imperial "
            "County, covering the half of the org's Far South/Border North footprint "
            "that every San Diego source misses. Rolling: 'Complete applications "
            "will be accepted until funds are exhausted' and 'Projects will be "
            "reviewed on a first-come first-served basis' \u2014 no deadline to race, "
            "but also no guarantee funds remain. FIT IS NARROWER THAN THE "
            "CANDIDATE SUGGESTS: the stated purpose is projects offering 'a "
            "justifiable public benefit, primarily through job creation and "
            "economic improvement,' and the three targ"
        ),
    ),
    Source(
        name="Port of San Diego \u2014 Tidelands Activation Program (TAP)",
        funder="Port of San Diego \u2014 Tidelands Activation Program (TAP)",
        url="https://www.portofsandiego.org/experiences/tidelands-activation-programs-tap",
        tier=Tier.GOVERNMENT,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "This category supports events put on by eligible non-profits, which "
            "are free and open to people of all ages. \u00b7 Real program, but the "
            "page is showing a cycle that has already closed: 'Deadline to apply: "
            "May 1, 2026 - 5:00 p.m.' for FY2026 (July 1 \u2013 June 30, 2026), which "
            "ended before today. Watch for the FY2027 cycle. NO DOLLAR AMOUNTS "
            "ARE PUBLISHED on the page \u2014 it references 'equal sponsorship' "
            "budgeted to each of the five member cities for Civic Events but "
            "gives no figures, and does not confirm the fee-waiver detail in the "
            "candidate description. Set award_min/award_max null and "
            "needs_human_check true; the award floor cannot be checked from this "
            "source, which is a real risk given the org's 10"
        ),
    ),
    Source(
        name="SANDAG \u2014 Grant Programs",
        funder="SANDAG \u2014 Grant Programs",
        url="https://www.sandag.org/funding/grant-programs",
        tier=Tier.GOVERNMENT,
        programs=[],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "SANDAG provides a variety of competitive grant programs to local "
            "jurisdictions, nonprofit organizations, community groups, and "
            "transportation partners. \u00b7 Page loads cleanly and is a genuine "
            "grant-programs hub, not a grantee list. Eligibility of nonprofits is "
            "stated explicitly in the lead paragraph. Regional by definition (San "
            "Diego County), so geography is a perfect fit. TWO IMPORTANT CAVEATS "
            "FOR THE REGISTRY. (1) THEMATIC FIT IS NEAR ZERO. Every named program "
            "is mobility, land use or habitat: Smart Growth Incentive, TransNet "
            "Environmental Mitigation Land Management, Active Transportation, "
            "Senior Mini-Grant, Housing Acceleration, Section 5310 Enhanced "
            "Mobility, Access for All, Flexible Fle"
        ),
    ),
    Source(
        name="San Diego County District Attorney \u2014 Community Grant Program",
        funder="San Diego County District Attorney \u2014 Community Grant Program",
        url="https://www.sdcda.org/office/Community-Grant-Program",
        tier=Tier.GOVERNMENT,
        programs=[Program.RESILIENCE, Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="government",
        notes=(
            "Grant funding up to $50,000 is available to selected organizations "
            "to support new projects and services over a twelve (12) month term "
            "to grow promising community-based solutions that produce positive "
            "results. \u00b7 CURRENTLY CLOSED \u2014 verbatim: 'The Community Grant Program "
            "is not currently accepting applications: Please refer back to this "
            "site for announcements regarding future solicitations.' Valid as a "
            "source page to watch for the next RFA; do NOT emit an open "
            "opportunity from it today. The top third of the page is an RFA 2026 "
            "grantee list, but the body below is a full program description with "
            "eligibility and funding rules, so it qualifies as a grants page. "
            "Eligibility verbatim: 'Organization"
        ),
    ),
    Source(
        name="Alliance for California Traditional Arts (ACTA) \u2014 Living Cultures Grant",
        funder="Alliance for California Traditional Arts (ACTA) \u2014 Living Cultures Grant",
        url="https://actaonline.org/program/living-cultures-grant/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="intermediary",
        notes=(
            "Be a nonprofit organization with 501(c)(3) status with an annual "
            "budget under $500,000 \u00b7 Confirmed on the funder's own page. "
            "California-only with no county exclusion, so San Diego and Imperial "
            "both qualify. Organizations/community groups/Tribal Nations receive "
            "$10,000; individual artists receive $7,500 (individual track is "
            "irrelevant to the org). Deadline on the page is April 27 2026 for a "
            "Sept 1 2026 - Aug 31 2027 grant period \u2014 that deadline has passed as "
            "of Aug 2 2026, so this is a spring-2027 target and the crawler "
            "should expect a closed cycle until roughly Feb-Mar 2027. HARD GATE: "
            "the $500,000 annual-budget ceiling. This is CLAUDE.md \u00a711 Q7 (the org's "
            "annual operating budget) \u2014 if the org is o"
        ),
    ),
    Source(
        name="California Humanities",
        funder="California Humanities",
        url="https://calhum.org/humanities-for-all/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="intermediary",
        notes=(
            "Eligibility is limited to California-based nonprofit organizations "
            "and non-federal public agencies. \u00b7 CRITICAL STATUS FLAG \u2014 the page "
            "currently states verbatim: 'California Humanities has suspended all "
            "programs and grant cycles until further notice.' Do not surface as "
            "an open opportunity until that banner clears; this is a watch-for- "
            "reopening source, not a live one. I could not corroborate the "
            "'partially reinstated' claim in the candidate description \u2014 "
            "calhum.org/grants/ returned stale 2021 content with no current "
            "status statement. Terms when live: 'Project Grants ($10,000 to "
            "$25,000) are awarded twice a year for public humanities projects up "
            "to two years from the award date.' MATCH REQUIR"
        ),
    ),
    Source(
        name="Creative West (formerly WESTAF)",
        funder="Creative West (formerly WESTAF)",
        url="https://wearecreativewest.org/grants/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="intermediary",
        notes=(
            "501(c)(3) nonprofit organization (per federal requirements, fiscal "
            "sponsorships are not permitted) \u00b7 Passes all four gates but I want "
            "to flag it hard before anyone gets excited. The /grants/ index page "
            "itself carries NO eligibility, award, or deadline text \u2014 it is just "
            "a program list (10 programs, 4 for organizations: Access "
            "accommodations, Living Traditions, Consortia Professional "
            "Development, TourWest). All substantive detail lives on "
            "tourwest.gosmart.org and creativewestgrants.gosmart.org, which block "
            "WebFetch with 403 and needed a browser user-agent via curl; the "
            "crawler will need the same treatment or it will parse an award-less, "
            "deadline-less page every week. Evidence quote and geogr"
        ),
    ),
    Source(
        name="San Diego Workforce Partnership",
        funder="San Diego Workforce Partnership",
        url="https://workforce.org/funding/",
        tier=Tier.INTERMEDIARY,
        programs=[Program.RULFP],
        confidence=Confidence.CONFIRMED,
        sector="intermediary",
        notes=(
            "The following organizations are recommended for funding in response "
            "to the Request for Proposals for Youth Workforce Development "
            "Services Responding to Identified Service Needs and Gaps : South Bay "
            "Community Services: $1,200,000 \u00b7 INCLUDE THE FUNDER, BUT THIS URL IS "
            "ABOUT TO GO DEAD \u2014 this is the most important finding on the page. "
            "Verbatim: 'SDWP is transitioning to PlanetBids as our centralized "
            "procurement platform. Moving forward, all RFPs and contracting "
            "opportunities will be posted exclusively on PlanetBids and will no "
            "longer be individually posted on our website.' Watching "
            "workforce.org/funding/ weekly will silently miss every future RFP. "
            "Before this goes in the registry, replace or"
        ),
    ),
    Source(
        name="Las Patronas",
        funder="Las Patronas",
        url="https://www.laspatronas.org/grants",
        tier=Tier.WARM,
        programs=[Program.ARTS],
        confidence=Confidence.CONFIRMED,
        sector="other",
        notes=(
            "We exclusively fund capital items for nonprofit organizations "
            "located in San Diego County. \u00b7 Open cycle confirmed live: 'Currently "
            "Accepting Applications. Application Deadline is August 28, 2026 at "
            "5:00 PM', with 'Major Grants for > $20,000 and Minor Grants \u2264 "
            "$20,000'. CAPITAL ITEMS ONLY \u2014 I pulled the requirements PDF and it "
            "is explicit: 'Las Patronas will not fund individuals, salaries, "
            "programs, training, warranties/service contracts, subscriptions, "
            "user licenses, separately purchased software, items for "
            "distribution, bank/investment accounts, endowments, general/reserve "
            "funds, operating costs, or vehicle wraps.' Items must have a useful "
            "life of at least three years and remain with the"
        ),
    ),
]
