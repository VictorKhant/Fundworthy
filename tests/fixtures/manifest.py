"""Ground truth for tests/fixtures/pages/*.html.

Every page here is a REAL funder page, fetched from a URL in the shipped registry
(agent/sd_funders.py, agent/sources.py) or a national/topical funder relevant to one of
the four program cards below — not synthetic prose. `expect_*` was established by a
human (or, for the batch added in this expansion, several independent model readings of
the raw fetched HTML plus a cross-check pass on any page flagged as ambiguous) reading
the actual fetched page, not by running the pipeline and copying its output. The whole
point of this file is to catch the pipeline disagreeing with what a careful reader can
see on the page.

The HTML is frozen at fetch time. A real page can change or disappear tomorrow — that
is a feature here, not a gap: this file tests "does the pipeline read THIS page
correctly", not "is this funder currently accepting applications", which is a
different, unanswerable-offline question. If a funder's page structure changes enough
that a fixture stops being representative, replace it; do not patch the expectation to
match a regression.

**Two questions, kept apart on purpose.** `expect_actionable` and `expect_relevant` are
different axes, and the first round of this harness conflated them into one field
(`expect_relevant_to_housing_org`) — which meant "the single best topical fit in this
set" and "an actual application you could start today" scored the same way. A funder's
homepage can be a perfect mission match and still describe nothing you can apply to; a
program can be exactly on-topic and still be explicitly suspended, invitation-only, or
past its deadline. `_TRIAGE_RULES` in agent/score.py asks one combined yes/no — "is this
page an open funding opportunity that this organization could actually apply for" — so
the expected triage answer for a (fixture, program) pair is the conjunction of both:
`expect_actionable AND expect_relevant[program]`. Keeping them separate here is what
lets `test_golden_fixtures.py`'s live check compute that conjunction itself, per
program, instead of trusting one hand-merged guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class PageFixture:
    slug: str                      # matches tests/fixtures/pages/{slug}.html
    url: str                       # the real URL this was fetched from
    funder: str
    note: str                      # what a human reading the page actually sees

    # Stage 1 (free): what apply_filters should decide.
    expect_rejected: bool
    expect_reject_reason: str | None = None   # agent.filters.Reject value, if rejected

    # What extraction should find — None means "not asserted", not "must be empty".
    # Only asserted where a human reading the page can state it with confidence.
    expect_award_max: int | None = None
    expect_deadline: date | None = None
    expect_has_apply_url: bool | None = None  # None = not asserted either way

    # Would a human reading THIS fetched page call it something a nonprofit can
    # actually apply to right now — an open call, an RFP, a rolling submission
    # process — as opposed to a homepage, a mission overview, a past-grantee
    # showcase, or a program stated as closed/suspended/invitation-only? None = not
    # asserted (not needed offline; only used by the live check below).
    expect_actionable: bool | None = None

    # Program slug -> is this page a plausible topical/mission fit for that program,
    # independent of whether the page itself is actionable. Keys are the slugs in
    # PROGRAMS below (hass / ARTS / RULFP / RESILIENCE). A slug not present here is
    # not asserted for that program. NOT verified by the offline suite — needs a live
    # Anthropic key, the way tests/calibration.py's full run does — but recording it
    # means a future live run has something concrete to score itself against. A
    # value of None (as opposed to a missing key) means "asserted as genuinely
    # ambiguous" — recorded on purpose, not left out by omission.
    expect_relevant: dict[str, bool | None] = field(default_factory=dict)

    reasoning: str = ""


FIXTURES: list[PageFixture] = [
    # ================================================================================
    # A — housing (New Destiny Housing, HASS). The original 12-fixture set.
    # ================================================================================

    # --- genuinely relevant to a supportive-housing nonprofit, no amount/deadline
    #     stated (both flags, not rejects) — the honest common case CLAUDE.md
    #     describes: most funder "priorities" pages state neither. -------------
    PageFixture(
        slug="hilton_foundation",
        url="https://www.hiltonfoundation.org/priorities/housing",
        funder="Conrad N. Hilton Foundation",
        note="A housing-priority overview page listing past grants as case studies "
             "(e.g. a $2.4M grant with 'Awarded Date: August, 2022') — no open "
             "application, no stated award range for a NEW applicant, no deadline.",
        expect_rejected=False,
        expect_award_max=None,  # the $2.4M figure is a past AWARDED grant, not an
                                # open call's range — must not be extracted as one
                                # (see test_deadline_amount_extraction.py's disqualifier
                                # test, which uses this exact real snippet).
        expect_deadline=None,
        expect_has_apply_url=True,  # a "Grant Search" link is present on the page
        expect_actionable=False,
        # CORRECTED after a live run (2026-08-07): this was True, on the reasoning
        # that housing is a named priority. That conflates "is this funder a good
        # topical fit" with "does THIS PAGE describe something you can apply to" —
        # triage answers the second question, and correctly said no: the page is
        # dominated by a past $2.4M grant case study with no open call described.
        # The same live run also caught a real bug this correction exists to
        # document: the SCORING call (a separate, later stage) initially returned
        # award_score=30/30 — reading that same $2.4M case-study figure as if it
        # were an offer to a new applicant, despite its own rationale saying "past
        # grant record." Fixed in _SCORING_RULES and re-verified (score corrected
        # from 53 to 37, award_score from 30 to null, twice, consistently). See
        # tests/test_scoring.py::test_award_score_ignores_a_past_grants_dollar_figure.
        expect_relevant={"hass": True, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="A housing-priority page, but this specific fetched page is a past-"
                 "grant case study with no open call, no application process, and no "
                 "current award figure described — triage correctly reads that as "
                 "'not an actionable opportunity' rather than 'good topical fit', "
                 "which are different questions. Confirmed live (Haiku triage + "
                 "Sonnet scoring, 2026-08-07): triage said no; scoring, once fixed, "
                 "agreed the award component was unknowable and dropped the total "
                 "from an inflated 53 to a correct 37.",
    ),
    PageFixture(
        slug="hud_coc",
        url="https://www.hud.gov/program_offices/comm_planning/coc",
        funder="HUD — Continuum of Care Program",
        note="The federal CoC program's own overview page — describes the program, "
             "not a single open NOFO with a stated amount or deadline. The second "
             "cached copy of this fetch has almost no body text at all (a Drupal "
             "settings blob instead of rendered content) — either way, nothing on "
             "the page describes a single open call.",
        expect_rejected=False,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        expect_relevant={"hass": True, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="CoC is THE core federal funding vehicle for homelessness/supportive "
                 "housing programs — about as close a fit as this product can find. "
                 "This overview page itself has no single open opportunity's specifics. "
                 "Confirmed live (2026-08-07): triage said yes ('HUD CoC funds "
                 "supportive housing and homelessness prevention services eligible "
                 "for HASS'); scoring gave fit=55/60, needs_human_check=True (the "
                 "page itself was thin navigation, honestly flagged rather than "
                 "scored on invented detail).",
    ),
    PageFixture(
        slug="enterprise_community",
        url="https://www.enterprisecommunity.org/",
        funder="Enterprise Community Partners",
        note="Homepage of a national affordable-housing intermediary — describes what "
             "they do broadly, not one open grant. Development-financing/CDFI/policy "
             "capabilities skew away from direct-service delivery (HASS's case "
             "management and eviction prevention).",
        expect_rejected=False,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        # CORRECTED after a live run (2026-08-07): see the note on hilton_foundation
        # above — the fixture is this organization's HOMEPAGE, and "a good topical
        # fit" and "an actionable opportunity" are different questions. Triage
        # correctly said no ("the organization homepage, not an open funding
        # opportunity"). The org would need to crawl a specific grants page, which
        # this fixture is not.
        expect_relevant={"hass": True, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="A national housing intermediary is a plausible PARTNER for a "
                 "supportive-housing nonprofit — its core mission (affordable housing "
                 "supply, racial equity, resident resilience) is broadly adjacent, "
                 "though its own capabilities skew toward development financing "
                 "rather than direct service delivery. But this specific fetched page "
                 "is a homepage with no described application — correctly not "
                 "actionable. Confirmed live (2026-08-07).",
    ),
    PageFixture(
        slug="melville_trust",
        url="https://melvilletrust.org/",
        funder="Melville Charitable Trust",
        note="Homepage of a foundation whose entire named mission is preventing and "
             "ending homelessness.",
        expect_rejected=False,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        # CORRECTED after a live run (2026-08-07) — same distinction as above. Being
        # the single best topical fit in this set does not make a bare homepage an
        # actionable opportunity, and triage correctly said so.
        expect_relevant={"hass": True, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="The single most on-mission FUNDER in this fixture set — but this "
                 "fetched page is its homepage, describing no open call. Confirmed "
                 "live (2026-08-07): triage said 'a homepage with no open grant "
                 "application call or deadline information', correctly declining to "
                 "treat topical mission alignment as a substitute for an actual "
                 "application process on the page in front of it.",
    ),

    # --- present, but a different program area — should pass stage 1's free
    #     filters (nothing here is against the rules) and then be the model's job to
    #     correctly rate as a weak fit for a housing-specific program. --------------
    PageFixture(
        slug="hearst_health",
        url="https://www.hearstfdn.org/health/funding-priorities",
        funder="Hearst Foundations",
        note="States 'Minimum grant size is $100,000' — a FLOOR, not a ceiling. No "
             "maximum award is stated anywhere on the page. Health funding "
             "priorities (hospitals, medical research, healthcare workforce), not "
             "housing, arts, civic leadership, or nonprofit-staff wellness.",
        expect_rejected=False,
        # CORRECTED in this expansion: this was `100_000`, on the reasoning that the
        # one dollar figure on the page IS a real, current figure. It is real — but
        # it is a stated MINIMUM ("Minimum grant size is $100,000"), and `award_max`
        # used to resolve to the same min()/max() over the one evidence value, so a
        # floor was reported as a ceiling. Fixed in agent/parse.py (`_FLOOR_ONLY_CUE`
        # / `Evidence.floor_only`) — see test_deadline_amount_extraction.py's
        # `test_a_lone_minimum_grant_size_does_not_become_the_award_max`, which uses
        # this exact real sentence. `award_min` is unaffected and still correctly
        # resolves to 100_000.
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=True,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="Health category funds hospitals, medical centers, healthcare "
                 "workforce and public-health/medical research, with a clear "
                 "institutional-scale preference (80% of Health dollars go to orgs "
                 "with budgets over $10M) — not a fit for HASS's DV housing services, "
                 "RISE Arts, RULFP's civic-leadership fellowship, or RESILIENCE's "
                 "nonprofit-staff wellness (patient-facing clinical care is not the "
                 "same thing as a nonprofit's own internal staff burnout support). "
                 "This is a genuine funding-priorities/eligibility page rather than a "
                 "single open call with a deadline, so it should also read as not "
                 "currently actionable. Confirmed live pre-fix (2026-08-07): triage "
                 "said no; scoring gave fit=10/60 and (before the floor/ceiling fix) "
                 "misread the $100,000 floor as a ceiling worth 30/30 on the award "
                 "component.",
    ),
    PageFixture(
        slug="calhum-hfa",
        url="https://calhum.org/humanities-for-all/",
        funder="California Humanities",
        note="States a real historical award range: 'Project Grants ($10,000 to "
             "$25,000).' The page's own schedule table shows the last real "
             "application window as Jan-Feb 2025, and it states in bold: 'All "
             "Programs Suspended... until further notice.' Humanities/arts funding, "
             "not housing, civic leadership, or wellness.",
        expect_rejected=False,
        expect_award_max=25_000,
        expect_deadline=None,
        expect_has_apply_url=True,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="A clean test of the free tier finding a real award range correctly "
                 "on a page whose program is nonetheless currently suspended — the "
                 "deterministic filters (floor/deadline/remove-list only) cannot "
                 "catch a suspension stated in prose, which is exactly the kind of "
                 "case the model tier exists for. Confirmed live (2026-08-07): "
                 "triage correctly read 'California Humanities has suspended all "
                 "programs and grant cycles', literally on the page, and declined it "
                 "for that reason as much as the mission mismatch with housing. "
                 "Public humanities programming (community dialogue, cultural "
                 "exhibits, storytelling) overlaps with RISE Arts' cultural-equity "
                 "mission closely enough to be program-relevant IF the program were "
                 "open — it is not, right now.",
    ),
    PageFixture(
        slug="jcf-cap",
        url="https://jcfsandiego.org/organizations/competitive-application-platform-cap/",
        funder="Jewish Community Foundation of San Diego",
        note="States two real award figures ($50,000 and $25,000 for different "
             "sub-programs). The real due-date table on this page is rendered by "
             "client-side JS and is not present in the static HTML — the free tier "
             "correctly finds nothing to extract for a deadline here, which is a "
             "known, accepted limitation (§5: no JS execution), not a parser bug.",
        expect_rejected=False,
        expect_award_max=50_000,
        expect_deadline=None,
        expect_has_apply_url=True,
        expect_relevant={"hass": None, "ARTS": None, "RULFP": None, "RESILIENCE": None},
        reasoning="Community foundation with broad categories — fit depends on "
                 "specifics not visible in the fetched HTML.",
    ),

    # --- the closed-grant fix, on real currently-shipped pages ----------------------
    PageFixture(
        slug="hdf-grants",
        url="https://thehdf.org/grants/",
        funder="The Human Dignity Foundation",
        note="States 'Deadline extended to: March 14, 2026' — real, but already "
             "passed relative to this suite's clock.",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_deadline=None,  # earliest_deadline is None once rejected as PASSED —
                               # the past date lives in the reject detail, not here.
        expect_actionable=False,
    ),
    PageFixture(
        slug="ivcf-rfps",
        url="https://www.ivcommunityfoundation.org/current-rfps/",
        funder="Imperial Valley Community Foundation",
        note="States an April 30, 2026 deadline, already passed relative to this "
             "suite's clock — found correctly by the OLD parser too; the old bug was "
             "discarding it as 'not stated' rather than rejecting it as closed.",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_actionable=False,
    ),
    PageFixture(
        slug="bscc-calvip",
        url="https://www.bscc.ca.gov/s_cpgpcalvipgrant/",
        funder="California Board of State and Community Corrections — CalVIP",
        note="States 'Proposals due 6/27/25' — a 2-digit-year date that a real bug in "
             "this pipeline (found while building this fixture set) parsed as the "
             "year 2125 before being fixed. Already passed relative to this suite's "
             "clock either way.",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_actionable=False,
    ),
    PageFixture(
        slug="sdpride-grants",
        url="https://sdpride.org/grants/",
        funder="San Diego Pride",
        note="States BOTH an open date (October 6, 2025) and a deadline (November 3, "
             "2025) in one run-on sentence with no punctuation between them — a real "
             "bug (also found while building this fixture set) reported the open date "
             "as if it were the deadline. Both have passed relative to this suite's "
             "clock, so the fixed behaviour rejects on the real deadline (Nov 3), not "
             "the open date (Oct 6) — asserted explicitly below.",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_actionable=False,
    ),

    # ================================================================================
    # B — arts (RISE Arts). Added in this expansion — real pages, all four domains
    # judged against every page so cross-domain negatives are honest, not assumed.
    # ================================================================================
    PageFixture(
        slug="acta-living-cultures",
        url="https://actaonline.org/program/living-cultures-grant/",
        funder="Alliance for California Traditional Arts",
        note="A real, fully-detailed grant program page: $10,000 fixed award for "
             "organizations/community groups/Tribal Nations (total pool $707,500 "
             "across 70-80 grants), application window March 3 - April 27, 2026. "
             "That window has already closed relative to today (2026-08-07).",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_award_max=10_000,
        expect_actionable=True,  # a real, specific program page — just past its cycle
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="Directly on-mission for RISE Arts: folk and traditional arts "
                 "practiced by individuals/orgs/Tribal Nations in California, aligned "
                 "with cultural equity and community-based arts practice. Genuinely "
                 "actionable as a program (not a homepage or case study) but its "
                 "2026-27 cycle closed April 27, 2026 — the free deadline filter "
                 "should reject it on that date, which is the correct outcome "
                 "regardless of the strong topical fit.",
    ),
    PageFixture(
        slug="nea-arts-projects",
        url="https://www.arts.gov/grants/grants-for-arts-projects",
        funder="National Endowment for the Arts",
        note="A genuine federal grant program page: GAP applicants $10,000-$100,000; "
             "Local Arts Agencies subgranting track up to $150,000. Two application "
             "cycles per year, both of this year's final deadlines (Feb 25 and July "
             "21, 2026) have already passed relative to today.",
        expect_rejected=True,
        expect_reject_reason="deadline_passed",
        expect_award_max=150_000,
        expect_actionable=True,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="NEA Grants for Arts Projects funds nonprofit arts organizations "
                 "broadly across all disciplines — directly on-mission for RISE Arts. "
                 "A real, detailed, actionable federal program, correctly rejected "
                 "here only because both of this year's cycles have already closed.",
    ),
    PageFixture(
        slug="warhol_guidelines",
        url="https://warholfoundation.org/grants/application-guidelines/",
        funder="The Andy Warhol Foundation for the Visual Arts",
        note="This page IS the application guidelines/instructions, with a real "
             "twice-yearly recurring deadline (postmark/email March 1 and September "
             "1 every year). Relative to today (2026-08-07) the next deadline "
             "(Sept 1, 2026) is about 3.5 weeks away — a live, open cycle. No dollar "
             "award figure is stated (only aggregate news-blurb totals elsewhere on "
             "the site). No online portal — applications go by mail or email, so "
             "there is no single 'apply here' URL to extract.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=True,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="Established visual-arts organizations broadly — a plausible fit "
                 "for RISE Arts if it meets the stated 5-year-history/$20k-budget "
                 "thresholds, though the Foundation is visual-arts-specific rather "
                 "than general/multidisciplinary. A genuinely open, actionable, "
                 "rolling twice-a-year process even though it names no dollar figure "
                 "and no portal URL — exactly the honest 'amount not stated' case "
                 "CLAUDE.md describes, not a reason to treat it as inactionable.",
    ),
    PageFixture(
        slug="dorisduke_loi",
        url="https://www.dorisduke.org/grants/letter-of-inquiry",
        funder="Doris Duke Foundation — Performing Arts",
        note="A real, live, rolling letter-of-inquiry submission mechanism — no fixed "
             "deadline, staff respond within two months. The page itself states "
             "candidly that 'the majority of DDF's grants are awarded through "
             "competitive (RFP) processes or by invitation' and 'very few grants "
             "result from unsolicited letters of inquiry.' No award amount is "
             "published; the LOI form asks the applicant to state their own "
             "requested amount.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=True,  # you can submit one today, even at long odds
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="This LOI page spans all of DDF's programs (Arts, Medical "
                 "Research, Environment, Child Well-being, Building Bridges), fetched "
                 "here under the 'Performing Arts' label — a plausible but marginal "
                 "fit given DDF's Arts program historically works through invitation/"
                 "regranting intermediaries more than open LOIs, and covers primarily "
                 "contemporary dance/jazz/theater rather than RISE Arts' broader "
                 "creative-placemaking/cultural-equity focus. Actionable in the "
                 "literal sense (a functioning portal exists today), but the page "
                 "itself signals low odds and no defined program terms — a good test "
                 "of whether the model treats 'you technically can submit' the same "
                 "as 'this is a real opportunity', which it should not conflate.",
    ),
    PageFixture(
        slug="usbank_play",
        url="https://www.usbank.com/about-us-bank/community/community-possible-grant-program/play-grants.html",
        funder="U.S. Bank Foundation — Community Possible (Play)",
        note="The program's own specific page (one of several named Community "
             "Possible categories), describing what it funds and offering a "
             "'Submit letter of interest' action plus downloadable guidelines. No "
             "dollar figure or deadline is stated anywhere on the page; the real "
             "apply action is a JS-driven button with no static href, so a correctly "
             "working parser finds no apply_url here — that is the honest outcome, "
             "not a miss.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=True,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="Play grants explicitly fund 'expanding access to the arts' — "
                 "visual/performing arts and cultural activities for underserved "
                 "communities, and enhancing 'economic vitality of the community via "
                 "local arts groups' — a strong thematic match for RISE Arts' "
                 "creative-placemaking/cultural-equity work. A real, live, named "
                 "grant program a nonprofit could act on today, not a generic "
                 "homepage, even with no amount, deadline, or capturable apply URL.",
    ),
    PageFixture(
        slug="ca-arts-council",
        url="https://arts.ca.gov/grants/",
        funder="California Arts Council",
        note="A purely navigational hub page listing links to sub-sections (Grant "
             "Programs & Applications, Grant Resources, FAQs, Grant Panels, Recent "
             "Grants Search, the SmartSimple portal). Names no specific grant "
             "program, amount, deadline, or eligibility criteria — it points "
             "elsewhere for all of that.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=True,  # the SmartSimple portal link is present and real
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="A state arts funder whose actual programs (linked from here, not "
                 "described here) would plausibly interest RISE Arts — but this page "
                 "is a directory, not a described opportunity, matching the same "
                 "pattern as hud_coc and enterprise_community above for the arts "
                 "domain: strong topical fit, zero actionable content on this "
                 "specific fetch.",
    ),
    PageFixture(
        slug="creativewest-grants",
        url="https://wearecreativewest.org/grants/",
        funder="Creative West",
        note="A hub/directory page listing roughly ten different named grant "
             "programs (Native Arts + Heritage Fund, Living Traditions, Creative "
             "West Artist Fund, TourWest, a National Leaders of Color Fellowship "
             "Program, and others), each with only a one-line description and a "
             "'Learn More'/'Apply at' link out — no amount, deadline, or eligibility "
             "detail is given on this page for any single one of them.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="Several listed programs (Living Traditions, Creative West Artist "
                 "Fund, TourWest) are on-mission for RISE Arts. The page also lists a "
                 "'National Leaders of Color Fellowship Program', which is adjacent "
                 "to but not the same thing as RULFP (a San Diego civic-leadership "
                 "fellowship, not an arts-sector one) — judged not a direct RULFP "
                 "match, flagged as the closest overlap in this set. A menu of "
                 "opportunities, not itself an actionable single call.",
    ),
    PageFixture(
        slug="surdna",
        url="https://surdna.org/",
        funder="Surdna Foundation",
        note="Homepage: a program overview (Inclusive Economies, Sustainable "
             "Environments, Thriving Cultures, Andrus Family Fund, Resilient "
             "Organizations Initiative) plus recent news. No specific RFP, award "
             "amount, deadline, or application process is described on the page "
             "itself — it points to a separate 'Prospective Grantees' page and a "
             "grants database for that.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="Surdna's 'Thriving Cultures' program is explicitly named as "
                 "supporting artists, artist collectives, and small arts "
                 "organizations working on cultural equity — a strong mission-level "
                 "fit for RISE Arts. Not a fit for RULFP specifically (Surdna's "
                 "programs are place/sector-based, not leadership-development-"
                 "branded) even though it funds capacity/resilience work broadly. "
                 "Homepage only — nothing actionable on this fetch.",
    ),
    PageFixture(
        slug="port-sd-tap",
        url="https://www.portofsandiego.org/experiences/tidelands-activation-programs-tap",
        funder="Port of San Diego — Tidelands Activation Program",
        note="A specific, currently-open, actionable opportunity: 'The application "
             "portal for Fiscal Year 2027 (July 1 - June 30, 2027) is open' with a "
             "named deadline (May 1, 2027 — still in the future relative to today, "
             "2026-08-07) and a live SmApply portal link. Event sponsorship for "
             "free, public special events on Port tidelands/parks — not a stated "
             "dollar figure, since it is sponsorship rather than a grant amount.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=date(2027, 5, 1),
        expect_has_apply_url=True,
        expect_actionable=True,
        expect_relevant={"hass": False, "ARTS": True, "RULFP": False, "RESILIENCE": False},
        reasoning="TAP is annual sponsorship for free public events on Port of San "
                 "Diego tidelands (Barrio Logan, Chula Vista, National City, "
                 "Coronado, Imperial Beach, San Diego proper) — event sponsorship "
                 "rather than general operating or program-services funding, and "
                 "geographically restricted to Port tidelands, but it is open to "
                 "eligible nonprofits and could plausibly fund a RISE Arts "
                 "creative-placemaking public event: a moderate but real fit. This is "
                 "the fixture set's clean 'should pass through and be found' case — "
                 "a genuinely open call with a real future deadline, not yet closed.",
    ),

    # ================================================================================
    # C — civic leadership (RULFP — RISE Urban Leadership Fellows Program). Real pages
    # where the mission fit is real but almost never backed by a specific, currently
    # open program on the fetched page itself.
    # ================================================================================
    PageFixture(
        slug="kellogg_leadership",
        url="https://www.wkkf.org/what-we-do/racial-equity/",
        funder="W.K. Kellogg Foundation — Racial Equity",
        note="A 'Racial Equity' mission/focus-area page: WKKF's theory of change on "
             "racial healing and equity for children/families, linking to generic "
             "site nav items (Grants & Opportunities, Fellowships, Grantseekers). "
             "No specific open program, RFP, application window, dollar figure, or "
             "eligibility criteria is named on this page.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": True, "RESILIENCE": False},
        reasoning="WKKF's racial equity/racial healing mission and its Fellowships "
                 "line item are a plausible mission-level fit for RULFP's BIPOC "
                 "civic-leadership development — the strongest topical fit in this "
                 "leadership batch — though the page gives no specifics to confirm "
                 "eligibility or geography for a San Diego fellowship. An overview "
                 "page, not a call.",
    ),
    PageFixture(
        slug="california_endowment",
        url="https://www.calendow.org/",
        funder="The California Endowment",
        note="Homepage: mission statement, aggregate giving stats ($4.1B total "
             "assets, $2.9B granted since inception across 22,000 grants — history, "
             "not a current per-award figure), and a scroll of recent blog/news "
             "posts. No specific open grant program, amount, deadline, or "
             "application process is on the page.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": True, "RESILIENCE": False},
        reasoning="TCE funds health equity, racial equity, and 'belonging' for "
                 "community-based organizations across California, and historically "
                 "(via Building Healthy Communities) has funded community leadership "
                 "and organizing work — a plausible mission-and-geography fit for "
                 "RULFP (San Diego, BIPOC civic leadership). TCE is California-only, "
                 "so it is a geographic mismatch for HASS (New York City). Homepage "
                 "only, nothing actionable on this fetch.",
    ),
    PageFixture(
        slug="annie_e_casey",
        url="https://www.aecf.org/",
        funder="Annie E. Casey Foundation",
        note="Homepage: nav menu (Strategies incl. 'Leadership Development'), a "
             "headline blog feed, generic site chrome. One 'Foster Community "
             "Change' strategy tile explicitly reads 'Building safe neighborhoods "
             "where children and families have access to quality education, jobs "
             "and housing' — the word 'housing' is literally on this page. One "
             "headline ('Application Call: Join Casey's Juvenile Justice Applied "
             "Leadership Network') appears in the scrolling feed with no amount, "
             "deadline, or eligibility content on this fetched page.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": True, "ARTS": False, "RULFP": True, "RESILIENCE": False},
        reasoning="A genuine double-domain fit, cross-checked by a second independent "
                 "read (2026-08-07): 'Leadership Development' is an explicit, named "
                 "AECF strategy with its own nav link and blurb — a solid mission-"
                 "level fit for RULFP — and the 'Foster Community Change' strategy "
                 "names housing directly, plausibly overlapping HASS's family-"
                 "stabilization work even though the page never says 'domestic "
                 "violence', 'eviction', or 'homeless'. No arts angle (RULFP is the "
                 "leadership program, not RISE Arts) and no wellness/burnout "
                 "language anywhere on the page. Homepage only — the one headline "
                 "close to an actual call gives no specifics on this fetch.",
    ),
    PageFixture(
        slug="james_irvine",
        url="https://www.irvine.org/our-focus/",
        funder="James Irvine Foundation",
        note="An 'Our Focus' overview page listing initiatives (Better Careers, "
             "Fair Work, Just Prosperity, Priority Communities, Leadership Awards, "
             "Exploratory Grantmaking) — and states outright: 'Grantseekers: We are "
             "not accepting unsolicited inquiries for our initiatives or current "
             "grantmaking at this time.' It links to a distinct 'Leadership Awards' "
             "microsite (not itself fetched here) via two DIFFERING URLs in "
             "different parts of the page.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=True,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": True, "RESILIENCE": False},
        reasoning="Irvine funds low-income worker economic mobility within "
                 "California only, so this is a geographic non-fit for HASS (NYC). "
                 "The named 'Leadership Awards' program ('recognizing and "
                 "supporting leaders advancing... solutions to California's most "
                 "significant challenges') is the closest fit in this batch to RULFP "
                 "— though it reads as an individual-recognition award rather than "
                 "an organizational fellowship grant, and this page explicitly "
                 "states current unsolicited grantmaking is closed. A good test of "
                 "whether the model catches an explicit closure statement in prose "
                 "that the deterministic filters cannot (no deadline to reject on).",
    ),

    # ================================================================================
    # D — nonprofit-leader wellness (RESILIENCE — RISE Resilience & Renewal). Note:
    # RESILIENCE was born out of Alliance Healthcare Foundation's i2 Challenge
    # (app/db.py: SEED_PROGRAMS), which makes alliance_healthcare below a real,
    # non-coincidental positive rather than a speculative guess.
    # ================================================================================
    PageFixture(
        slug="durfee_foundation",
        url="https://durfee.org/",
        funder="Durfee Foundation — Sabbatical Program",
        note="Homepage: nav menu, hero banner, a 'latest announcements' feed, and a "
             "grid of past Lark Awards grantee bios. Not the Sabbatical program's "
             "own page — states no amount, deadline, or application instructions "
             "for Sabbatical, and explicitly flags two OTHER programs (Lark Awards, "
             "Stanton Fellowship) as 'applications now closed.'",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": True},
        reasoning="Durfee's Sabbatical Award (a paid rest/renewal award for a "
                 "nonprofit's executive director) is topically an excellent "
                 "conceptual match for RESILIENCE's leader-burnout/renewal mission "
                 "— but Durfee funds Los Angeles County nonprofits specifically, not "
                 "San Diego, so geographic eligibility is doubtful. This fetched "
                 "page is the homepage, not the Sabbatical page, and states nothing "
                 "about it directly.",
    ),
    PageFixture(
        slug="california_wellness",
        url="https://www.calwellness.org/",
        funder="The California Wellness Foundation",
        note="Homepage: hero story, a rotating news/blog feed, a one-line 'what is "
             "wellness?' blurb, an email signup. No specific grant program, amount, "
             "deadline, or eligibility criteria appears anywhere in the fetched "
             "HTML. The real 'Apply for a Grant' link exists in the site nav but is "
             "boilerplate chrome, not body content, so it correctly does not "
             "surface as an apply_url here.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": True},
        reasoning="A large California health-equity funder whose mission language "
                 "('wellness means health of body, mind and spirit... justice, "
                 "equity and voice') is thematically adjacent to RESILIENCE's "
                 "wellness framing, and it is statewide so San Diego orgs are "
                 "geographically eligible in principle — but this page states no "
                 "actual funding stream, amount, or process, so the fit is "
                 "speculative based on general mission language alone.",
    ),
    PageFixture(
        slug="alliance_healthcare",
        url="https://alliancehf.org/innovation-initiative-i2/",
        funder="Alliance Healthcare Foundation — Innovation Initiative",
        note="A program-overview-plus-past-grantees showcase for the i2 Challenge: "
             "a short concept description and a table of past grantees 2010-2025 "
             "(historical range $440K-$4.5M cumulative, ~$1M being the most common "
             "recent figure). No statement that a new round is currently open, no "
             "eligibility criteria, no deadline, and no application mechanism — "
             "reads as 'here's what we've funded', not a live call.",
        expect_rejected=False,
        expect_award_max=None,  # the $1M-ish figures describe PAST grantees, the
                                # same historical-record pattern as hilton_foundation
                                # above — not a current per-award ceiling.
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": True},
        reasoning="Not a speculative fit — this is the funder RESILIENCE was "
                 "literally BORN out of (app/db.py's SEED_PROGRAMS: RESILIENCE's "
                 "summary states it originated from 'Alliance Healthcare "
                 "Foundation's i2 Challenge'), so RULFP-style program-lineage makes "
                 "this the strongest possible topical match in this set for "
                 "RESILIENCE even though the i2 program itself funds scalable "
                 "health-equity service innovations for the community rather than a "
                 "nonprofit's own internal staff-wellness program specifically. A "
                 "past-grantees showcase, not a currently open call.",
    ),
    PageFixture(
        slug="hcai-bhp",
        url="https://hcai.ca.gov/workforce/financial-assistance/grants/bhp/",
        funder="CA Dept of Health Care Access and Information — Behavioral Health Workforce",
        note="A directory of HCAI behavioral-health workforce programs. The one "
             "program with an explicit status ('Peer Personnel Training and "
             "Placement Program') is stated as 'Application Cycle: CLOSED... check "
             "back... January 2027.' Every other program listed is explicitly "
             "labeled 'do not have future planned funding at this time.'",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="These are clinical/educational workforce-pipeline grants — "
                 "funding for psychiatry residency slots, PMHNP training, "
                 "peer-support-specialist certification — awarded to hospitals, "
                 "universities, and county behavioral health systems, not general "
                 "operating or capacity-building funding for a nonprofit's own "
                 "staff wellness program. Even setting aside that everything listed "
                 "is closed or has no future funding, the program design does not "
                 "match RESILIENCE (which is about the nonprofit's own workforce, "
                 "not clinical training pipelines for licensed professionals) — a "
                 "genuine all-four-false negative, and a good test that topical "
                 "adjacency ('behavioral health', 'wellness') does not get "
                 "auto-matched without checking who the money is actually for.",
    ),

    # ================================================================================
    # Cross-domain negatives — real pages picked for reasons OTHER than a housing/
    # arts/leadership/wellness angle (procurement, infrastructure, a broken fetch, a
    # geographically- or eligibility-excluded funder) so every program's "no" answers
    # are exercised on real pages, not assumed by omission.
    # ================================================================================
    PageFixture(
        slug="robin_hood_nyc",
        url="https://www.robinhood.org/",
        funder="Robin Hood",
        note="Homepage: mission statement ('NYC's largest poverty-fighting "
             "organization'), aggregate impact figures ('$140 million in 515 "
             "grants... 2025' and '$17.5M in Q2 2026 grants' — both program-wide "
             "totals, not a per-award figure), news highlights, a donation "
             "call-to-action. Links to 'Become a Grantee' but does not itself "
             "describe an open application, eligibility, amount, or deadline.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": True, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="Robin Hood is explicitly NYC-based and funds direct anti-poverty "
                 "service organizations across the city — a strong geographic and "
                 "mission match for HASS. No connection to San Diego arts "
                 "programming, a San Diego leadership fellowship, or nonprofit-"
                 "staff wellness — all three are San Diego- or internal-workforce-"
                 "focused and outside Robin Hood's NYC anti-poverty scope. Homepage "
                 "only, no actionable content on this fetch. (Also a real "
                 "apply_url bug worth knowing about separately: a naive parser can "
                 "pick a Q2-grantmaking NEWS ARTICLE as the apply link instead of "
                 "the actual 'Become a Grantee' page — an announcement of past "
                 "awards is not an application entry point.)",
    ),
    PageFixture(
        slug="sdge-guidelines",
        url="https://www.sdge.com/more-information/community/funding-guidelines",
        funder="San Diego Gas & Electric Corporate Giving",
        note="A real, live corporate-giving guidelines page: instructs applicants "
             "to email the Community Relations team, then describes an online "
             "application system with login/save-and-resume. No amount or "
             "deadline stated — rolling/ongoing giving, no cycle or date named. "
             "The page explicitly restricts funding to San Diego County / south "
             "Orange County, and explicitly states it does NOT fund 'programs "
             "primarily focused on the arts and humanities.'",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=True,  # more than a homepage — a real, if informal, path
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="A four-way negative stated explicitly in the funder's own words, "
                 "not inferred: geographically excludes HASS (NYC), and the page "
                 "itself rules out arts and humanities funding by name. Listed "
                 "giving areas (environment, emergency preparedness/public safety, "
                 "STEM education, workforce/economic-prosperity) don't match "
                 "RULFP's civic-leadership/DEIA focus or RESILIENCE's nonprofit-"
                 "staff wellness. A useful negative precisely because it has real, "
                 "if informal, actionability (an email address, a described login "
                 "system) — actionable does not have to mean relevant.",
    ),
    PageFixture(
        slug="sandag-grants",
        url="https://www.sandag.org/funding/grant-programs",
        funder="SANDAG — Grant Programs",
        note="A hub/directory page listing categories of SANDAG's grant programs "
             "(Active Transportation, Smart Growth & Housing, Specialized "
             "Transportation, TransNet Land Management, Housing Acceleration "
             "Program, Section 5310) and explaining the general BidNet Direct "
             "solicitation process. Names no specific open call, amount, or "
             "deadline.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="SANDAG funds transportation, active-mobility, and regional "
                 "housing-PRODUCTION infrastructure grants to jurisdictions/"
                 "agencies — its 'Housing Acceleration Program' is about housing "
                 "production/planning at the government-agency level, not "
                 "supportive-housing SERVICES for individuals, so it is not a "
                 "match for HASS despite the shared word 'housing.' Nothing here "
                 "matches arts, civic leadership fellowships, or nonprofit-staff "
                 "wellness either. A directory page with no single actionable call.",
    ),
    PageFixture(
        slug="sony-createaction",
        url="https://alphauniverse.com/createaction/",
        funder="Sony Electronics — CREATE ACTION",
        note="A marketing/announcement article displaying a list of already-"
             "selected past 'Grant Recipients' (35+ organizations, published as an "
             "article dated 2025-08-05). No application process, no deadline, no "
             "dollar figures, and no way to apply — a case-study/results showcase "
             "of a program cycle that has already run its course.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_has_apply_url=False,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="CREATE ACTION supports grassroots community organizations "
                 "broadly (storytelling, digital divide, youth robotics, film "
                 "camps, civic advocacy) rather than being an arts-sector funder "
                 "specifically, so even RISE Arts is at best a weak/uncertain "
                 "match — moot regardless, since the page is a past-results "
                 "showcase with nothing to apply to.",
    ),
    PageFixture(
        slug="packard_org_effectiveness",
        url="https://www.packard.org/what-we-fund/organizational-effectiveness/",
        funder="David and Lucile Packard Foundation — Organizational Effectiveness",
        note="IMPORTANT: this fetch did not land on an Organizational Effectiveness "
             "page. The canonical URL embedded in the fetched HTML is "
             "https://www.packard.org/approach/, titled 'Approach' — the "
             "Foundation's general mission/values/program-areas overview. The "
             "string 'organizational effectiveness' does not appear anywhere in "
             "the fetched text; the OE-specific page appears to have moved.",
        expect_rejected=False,
        expect_award_max=None,
        expect_deadline=None,
        expect_actionable=False,
        expect_relevant={"hass": False, "ARTS": False, "RULFP": False, "RESILIENCE": False},
        reasoning="Cannot honestly judge fit for Organizational Effectiveness "
                 "funding (which, by reputation, supports nonprofit capacity-"
                 "building and could plausibly touch RESILIENCE) because this "
                 "fetched page contains none of that program's actual content — "
                 "only the Foundation's generic mission statement. Marked false "
                 "for all four programs because there is nothing programmatic on "
                 "the page to match against, not as a verdict on the real program: "
                 "a data/fetch-drift problem (a URL that no longer resolves where "
                 "the registry thinks it does) is a real, recurring failure mode "
                 "worth having a fixture for on its own.",
    ),
]


# The organization each program card belongs to. Every fixture above is judged
# against all four program slugs at once (`expect_relevant`), because a funder page
# does not know or care which of an org's programs it might fit — the model has to
# tell them apart on the page's own content every time, and a fixture set that only
# ever asked about one program could never catch it mismatching across a real
# multi-program org.

# The test organization for HASS: New Destiny Housing, a real NYC supportive-housing
# nonprofit (https://newdestinyhousing.org/hass/ — the program the product owner used
# to test this pipeline by hand). Not synthetic — the summary below is drawn from the
# org's own saved program page (tests/fixtures/pages/new_destiny_program.html), the
# same way a real user would paste this link into the assistant (app/assistant.py) and
# get a drafted card back.
NEW_DESTINY_HOUSING_PROGRAM = {
    "slug": "hass",
    "name": "Housing Access and Stabilization Services (HASS)",
    "summary": (
        "Supportive housing and homelessness prevention services for survivors of "
        "domestic violence and other at-risk families in New York City — housing "
        "placement, eviction prevention, and case management toward stable, "
        "permanent housing."
    ),
    "what_it_funds": (
        "Case management staff, rental assistance/subsidies, housing placement "
        "services, and support services connected to permanent supportive housing."
    ),
    "keywords": [
        "supportive housing", "homelessness prevention", "domestic violence survivors",
        "eviction prevention", "permanent housing", "housing placement",
        "case management",
    ],
    "funder_types": ["government", "foundation", "community_foundation"],
}

# The other three program cards belong to RISE San Diego, the pilot organization
# CLAUDE.md §1-2 describes — real cards, taken verbatim from app/db.py's
# `SEED_PROGRAMS` (what a fresh RISE San Diego account actually seeds), not invented
# for this test file. RESILIENCE's own summary states it was "born out of Alliance
# Healthcare Foundation's i2 Challenge" — which is why `alliance_healthcare` above is
# marked as a real, non-speculative match for it rather than a guess.
RISE_ARTS_PROGRAM = {
    "slug": "ARTS",
    "name": "RISE Arts",
    "summary": "Arts and social justice with artists from historically marginalized "
              "communities.",
    "what_it_funds": "Creative placemaking, cultural equity, arts capacity building.",
    "keywords": ["arts and social justice", "historically marginalized artists",
                "creative placemaking", "cultural equity", "arts capacity building"],
    "funder_types": ["public_agency", "private_foundation"],
}

RULFP_PROGRAM = {
    "slug": "RULFP",
    "name": "RISE Urban Leadership Fellows Program",
    "summary": "Leadership pipeline for resident-led civic engagement in San Diego "
              "and Imperial Counties.",
    "what_it_funds": "Cohort fellowship delivery, BIPOC leadership development, "
                    "DEIA capacity building.",
    "keywords": ["leadership pipeline", "adaptive leadership",
                "resident-led civic engagement", "BIPOC leadership development",
                "cohort fellowship", "DEIA capacity building"],
    "funder_types": ["private_foundation", "community"],
}

RESILIENCE_PROGRAM = {
    "slug": "RESILIENCE",
    "name": "RISE Resilience & Renewal",
    "summary": "Whole-body leadership and burnout recovery for nonprofit leaders. "
              "Born out of Alliance Healthcare Foundation's i2 Challenge.",
    "what_it_funds": "Somatic practice, wellness programming, workforce retention.",
    "keywords": ["nonprofit leader burnout", "whole-body leadership",
                "somatic practice", "polyvagal theory", "wellness",
                "workforce retention", "health tech"],
    "funder_types": ["private_foundation", "government"],
}

# slug -> program dict, and slug -> the org context that program is evaluated under
# (name, location). `test_golden_fixtures.py` builds one Config per program from this.
PROGRAMS: dict[str, dict] = {
    "hass": NEW_DESTINY_HOUSING_PROGRAM,
    "ARTS": RISE_ARTS_PROGRAM,
    "RULFP": RULFP_PROGRAM,
    "RESILIENCE": RESILIENCE_PROGRAM,
}
ORG_FOR_PROGRAM: dict[str, tuple[str, str]] = {
    "hass": ("New Destiny Housing", "New York, New York"),
    "ARTS": ("RISE San Diego", "San Diego, California"),
    "RULFP": ("RISE San Diego", "San Diego, California"),
    "RESILIENCE": ("RISE San Diego", "San Diego, California"),
}
