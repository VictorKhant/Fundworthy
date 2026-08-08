"""apply_url — the link a nonprofit actually clicks to apply, separate from
source_url (agent/parse.py: find_apply_link). Offline, no key, no network.

Found by fetching 62 real funder pages from the shipped registry and checking where
their real "Apply" links actually point. 8 of 62 — 13% — point at a dedicated grants-
management vendor (Fluxx, Submittable, SM Apply, GrantRequest) on a completely
different host than the funder's own site. `source_url` must stay the funder's own
page (CLAUDE.md §6), so it can never be that link without breaking the rule that makes
it trustworthy — this is a second, separate fact instead.

It needs no model and no verify.py gate: every candidate is a real href already
present in the fetched HTML, so it is self-evidencing the same way a quoted sentence
is. The tests below are grounded in real anchor text and real hrefs copied from those
62 pages, attributed by funder.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.parse import find_apply_link, parse_page  # noqa: E402


# --- the case that motivated this: off-domain portal links ---------------------

def test_a_known_portal_link_is_found_even_off_domain():
    """Kaiser Permanente Southern California: the real "Yes! Apply Now" button on
    their funding-opportunities page points at grantrequest.com, not kp.org."""
    links = [
        ("/about", "About Us"),
        ("https://www.grantrequest.com/SID_946?SA=SNA&FID=35239", "Yes! Apply Now"),
    ]
    found = find_apply_link("https://community.kp.org/grants", links)
    assert found == "https://www.grantrequest.com/SID_946?SA=SNA&FID=35239"


def test_a_fluxx_registration_link_is_found():
    """The Kresge Foundation routes applications through their Fluxx portal on a
    completely different subdomain."""
    links = [
        ("/resource/fluxx-portal-instructions/", "LEARN HOW TO USE FLUXX"),
        ("https://kresge.fluxx.io/lois/new", "REGISTER HERE"),
    ]
    found = find_apply_link("https://kresge.org/grants/", links)
    assert found == "https://kresge.fluxx.io/lois/new"


def test_a_submittable_link_is_found():
    """Grossmont Healthcare District routes applications through Submittable."""
    links = [
        ("https://grossmonthealthcare.submittable.com/submit", "Apply"),
    ]
    found = find_apply_link("https://grossmonthealthcare-ca2.specialdistrict.org/grants",
                            links)
    assert found == "https://grossmonthealthcare.submittable.com/submit"


# --- the common case: same-domain relative apply links -------------------------

def test_a_same_domain_relative_apply_link_is_resolved():
    """S. Mark Taper Foundation's real apply link is `apply.html`, relative, on their
    own domain — the ordinary case this must not regress while fixing the off-domain
    one."""
    links = [("apply.html", "Apply")]
    found = find_apply_link("https://www.smtfoundation.org/guidelines.html", links)
    assert found == "https://www.smtfoundation.org/apply.html"


# --- self-evidencing: never invents a link the page did not offer ---------------

def test_no_apply_url_when_nothing_on_the_page_looks_like_one():
    links = [("/about", "About Us"), ("/staff", "Our Team"), ("/contact", "Contact")]
    assert find_apply_link("https://example.invalid/grants", links) is None


def test_mailto_and_javascript_links_are_never_returned():
    links = [("mailto:apply@example.invalid", "Apply by Email"),
             ("javascript:void(0)", "Apply Now")]
    assert find_apply_link("https://example.invalid/grants", links) is None


def test_a_pdf_apply_link_is_not_returned():
    """§5: a PDF fetched as HTML decodes to binary noise. The same reasoning applies
    here — an apply "link" that is actually a PDF is not a page anyone can act on
    through this product yet."""
    links = [("/apply-form.pdf", "Apply Now")]
    assert find_apply_link("https://example.invalid/grants", links) is None


def test_a_link_back_to_the_page_itself_is_not_returned():
    links = [("https://example.invalid/grants", "Learn More")]
    assert find_apply_link("https://example.invalid/grants", links) is None


# --- the fragile tie this fix specifically hardened -----------------------------

def test_a_grant_seekers_page_beats_a_grant_recipients_page():
    """The Parker Foundation, verbatim: both "Grant Seekers" and "Grant Recipients"
    match the same weak generic hint, and "Grant Recipients" — a past-grantees page,
    not an apply path — must never win regardless of which one the page lists
    first."""
    links = [
        ("/grant-making/grant-recipients/", "Grant Recipients"),
        ("/grant-making/grant-seekers/", "Grant Seekers"),
    ]
    found = find_apply_link("https://theparkerfoundation.org/grant-making/", links)
    assert found == "https://theparkerfoundation.org/grant-making/grant-seekers"

    # And order must not matter — the exclusion, not document position, is what
    # decides this.
    reversed_links = list(reversed(links))
    found_reversed = find_apply_link("https://theparkerfoundation.org/grant-making/",
                                     reversed_links)
    assert found_reversed == found


def test_a_grant_amount_case_study_is_not_picked_as_the_apply_link():
    """A "past grants" case-study page (Hilton Foundation's real page structure) must
    not be selected even when it is the only grant-related link available — an
    unhelpful destination is worse than no apply link at all when the alternative is
    the honest `None`."""
    links = [("/grants/2400000-housing-grant-2022", "$2.4M Grant Awarded — Case Study")]
    assert find_apply_link("https://example.invalid/priorities/housing", links) is None


# --- strong signal beats weak signal ---------------------------------------------

def test_a_real_apply_anchor_beats_a_generic_grant_link():
    links = [
        ("/priorities", "Funding Priorities"),
        ("/apply-now", "Apply Now"),
    ]
    found = find_apply_link("https://example.invalid/grants", links)
    assert found == "https://example.invalid/apply-now"


# --- end to end through parse_page -----------------------------------------------

def test_parse_page_surfaces_apply_url_separately_from_source_url():
    html = (
        "<html><head><title>Community Grants</title></head><body>"
        "<p>Grants of up to $50,000 are awarded to nonprofits.</p>"
        '<a href="https://portal.example-vendor.com/apply/123">Apply Now</a>'
        "</body></html>"
    )
    page = parse_page("https://example.invalid/grants", html)
    assert page.url == "https://example.invalid/grants"
    assert page.apply_url == "https://portal.example-vendor.com/apply/123"
    assert page.apply_url != page.url


def test_parse_page_apply_url_is_none_when_the_page_has_no_clear_apply_link():
    html = (
        "<html><head><title>About Us</title></head><body>"
        "<p>We have been serving the community since 1990.</p>"
        "</body></html>"
    )
    page = parse_page("https://example.invalid/about", html)
    assert page.apply_url is None
