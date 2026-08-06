"""The checks that decide whether a shared funder is offered to anybody.

Offline. `check_page` is exercised against a stubbed fetcher rather than the network,
because the thing under test is the *judgement* — what counts as a usable grants page and
what the resulting sentence says — not whether httpx works.

The sentence matters as much as the boolean. It is printed verbatim on somebody else's
Discover page as the only evidence behind a stranger's suggestion, so it has to be a
statement of fact with a date, never a verdict.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.funder_check import check_page  # noqa: E402

GRANTS_PAGE = """
<html><body>
<h1>Community Grants Program</h1>
<p>The Foundation awards grants of up to $50,000 to eligible nonprofit organizations.
Applications open each spring. The deadline for the current cycle is March 15, 2027.
Read the eligibility criteria before you apply; the application asks for a proposal
and a budget.</p>
<p>Grants are awarded twice a year to applicants working in our region. Please review
the funding guidelines carefully before submitting your application.</p>
</body></html>
"""

# Long enough to clear MIN_TEXT, so this exercises the "not about grants" branch rather
# than the "almost nothing on it" one. Both are correct rejections; they are different
# sentences and the person reading them needs the right one.
A_HOMEPAGE = """
<html><body><h1>Welcome to Our Company</h1>
<p>We make excellent widgets for discerning customers around the world. Our team has
been building quality products since 1994, and we are proud of our long history of
service to the community and our many satisfied customers everywhere. Every widget
leaves our workshop having passed a thorough inspection by one of our craftspeople.</p>
<p>Our head office sits on the river, and visitors are always welcome to come and see
how the workshop runs. We employ over two hundred people locally and work with
suppliers in eleven countries, most of whom we have known for decades.</p>
<p>If you would like to talk to somebody about a bulk order, our sales team answers
the phone between nine and five on weekdays, and there is a contact form below.</p>
</body></html>
"""


def _stub_fetch(monkeypatch, *, ok=True, html=GRANTS_PAGE, error=None, status=200):
    class _Fetcher:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return SimpleNamespace(ok=ok, html=html, error=error, status=status,
                                   final_url=url)

    monkeypatch.setattr("agent.fetch.Fetcher", _Fetcher)


def run(coro):
    return asyncio.run(coro)


def test_a_real_grants_page_passes_and_says_what_it_saw(monkeypatch):
    _stub_fetch(monkeypatch)
    ok, note = run(check_page("https://example.invalid/grants"))

    assert ok is True
    assert "opened" in note
    # A statement about the page, never a judgement about the funder.
    for forbidden in ("verified", "trusted", "legitimate", "approved", "safe"):
        assert forbidden not in note.lower(), f"{note!r} claims more than we know"


def test_a_funder_with_no_web_address_is_not_shareable(monkeypatch):
    ok, note = run(check_page(None))
    assert ok is False and "nothing for anyone to open" in note

    ok, note = run(check_page("   "))
    assert ok is False


def test_a_page_that_does_not_load_is_kept_out(monkeypatch):
    """Failing is disqualifying. A dead link wastes the next person's time for certain."""
    _stub_fetch(monkeypatch, ok=False, html=None, error="http_404", status=404)
    ok, note = run(check_page("https://example.invalid/gone"))
    assert ok is False and "not there any more" in note


def test_a_site_that_asks_not_to_be_read_says_so_rather_than_looking_broken(monkeypatch):
    """"We are not allowed to read it" and "it is not there" are different facts, and
    only one of them suggests the link is wrong."""
    _stub_fetch(monkeypatch, ok=False, html=None, error="robots_disallowed")
    ok, note = run(check_page("https://example.invalid/private"))
    assert ok is False and "asks not to be read" in note


@pytest.mark.parametrize("error,status,expected", [
    ("ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
     "certificate has expired (_ssl.c:1006)", None, "security certificate"),
    ("blocked_url: could not look up nope.invalid", None, "does not exist"),
    ("ConnectTimeout: timed out", None, "took too long"),
    ("http_404", 404, "not there any more"),
    ("http_403", 403, "refused to let us"),
    ("http_503", 503, "returned an error"),
    ("too_many_redirects", None, "keeps redirecting"),
    ("unreadable_content_type:application/pdf", None, "a file rather than a web page"),
])
def test_a_failure_says_what_to_do_about_it_not_what_python_saw(monkeypatch, error,
                                                                status, expected):
    """This sentence is shown to a nonprofit administrator and its whole job is to tell
    them what to do next.

    The first draft printed the exception repr — "(ConnectError: [SSL:
    CERTIFICATE_VERIFY_FAILED] ... (_ssl.c:1006))" — which is accurate, actionable by
    nobody, and exactly the register CLAUDE.md's binding constraint rules out.
    """
    _stub_fetch(monkeypatch, ok=False, html=None, error=error, status=status)
    ok, note = run(check_page("https://example.invalid/x"))

    assert ok is False
    assert expected in note
    for jargon in ("_ssl.c", "ConnectError", "Traceback", "http_4", "http_5"):
        assert jargon not in note, f"{note!r} still reads like a stack trace"


def test_an_unfamiliar_failure_keeps_the_raw_reason_rather_than_hiding_it(monkeypatch):
    """A reason we have not seen before is more useful ugly than absent — it is how the
    next case gets added to the list."""
    _stub_fetch(monkeypatch, ok=False, html=None, error="something entirely new")
    ok, note = run(check_page("https://example.invalid/x"))
    assert ok is False and "something entirely new" in note


def test_a_page_that_is_not_about_grants_is_kept_out(monkeypatch):
    """The commonest honest mistake: somebody pastes a funder's homepage."""
    _stub_fetch(monkeypatch, html=A_HOMEPAGE)
    ok, note = run(check_page("https://example.invalid/"))
    assert ok is False and "does not look like it is about grants" in note


def test_an_almost_empty_page_is_kept_out(monkeypatch):
    _stub_fetch(monkeypatch, html="<html><body><p>Coming soon</p></body></html>")
    ok, note = run(check_page("https://example.invalid/soon"))
    assert ok is False and "almost nothing on it" in note


def test_a_broken_host_is_a_result_not_an_exception(monkeypatch):
    """This runs in a background thread over somebody else's website. A DNS blip must
    not become an exception in a request handler."""
    class _Exploding:
        async def __aenter__(self):
            raise OSError("nodename nor servname provided")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("agent.fetch.Fetcher", _Exploding)
    ok, note = run(check_page("https://example.invalid/x"))
    assert ok is False and "could not be opened" in note


# --- the false negative that started this --------------------------------------

# Reduced from the real macfound.org/grants page. The whole grant vocabulary is "grant"
# and "grants" — two surface forms of one word — which is precisely what the first
# version of the rule could not see.
A_REAL_FOUNDATION = """
<html><head><title>Grant Search - MacArthur Foundation</title></head><body>
<h1>Grant Search</h1>
<p>Search our database of grants. MacArthur has awarded more than $100,000,000 in
grants across our programs this year. Use the filters to narrow by program area,
region and year. Each grant record shows the recipient organization, the amount and
the period covered.</p>
<p>Our grantmaking supports organizations working on climate solutions, criminal
justice, nuclear challenges and local initiatives in Chicago and Nigeria. Browse the
grant list below or download the full dataset.</p>
</body></html>
"""


def test_a_page_titled_grant_search_is_a_grants_page(monkeypatch):
    """Reported: MacArthur Foundation was rejected as "not about grants".

    3,116 characters of real text, a page called "Grant Search", at a URL ending
    `/grants`, stating a figure — and the rule wanted three *distinct strings* from its
    vocabulary list and found "grant" and "grants", which are one word. Counting surface
    forms also rewarded rambling pages over focused ones, which is backwards.
    """
    _stub_fetch(monkeypatch, html=A_REAL_FOUNDATION)
    ok, note = run(check_page("https://www.macfound.org/grants"))

    assert ok is True, note
    assert "opened" in note


def test_the_title_and_the_address_count_even_when_the_prose_is_thin(monkeypatch):
    """The three strongest signals are not in the body: what the page is called, what
    the address says, and whether the parser could pull a real figure off it."""
    thin = ("<html><head><title>Grants</title></head><body><p>" + ("Our grant "
            "programme supports local organizations. " * 12) + "</p></body></html>")
    _stub_fetch(monkeypatch, html=thin)
    assert run(check_page("https://example.invalid/grants"))[0] is True


def test_a_funders_front_page_is_refused_with_advice_not_a_shrug(monkeypatch):
    """A homepage is still the wrong link — the funder editor asks for the grants page —
    but "does not look like it is about grants" is a confusing thing to hear about a
    foundation's own website. Say which page to use instead."""
    homepage = ("<html><head><title>The Example Foundation</title></head><body><p>"
                + ("We are a private foundation working with communities across the "
                   "region. Our funding supports local organizations. " * 6)
                + "</p></body></html>")
    _stub_fetch(monkeypatch, html=homepage)
    ok, note = run(check_page("https://example.invalid/"))

    assert ok is False
    assert "front page" in note and "grants page" in note


def test_a_page_with_nothing_to_do_with_grants_still_fails(monkeypatch):
    """The loosening must not turn the check into a rubber stamp."""
    _stub_fetch(monkeypatch, html=A_HOMEPAGE)
    assert run(check_page("https://example.invalid/about"))[0] is False


def test_plurals_are_one_word_not_two():
    from app.funder_check import _stem

    assert _stem("grants") == _stem("grant")
    assert _stem("awards") == _stem("award")
    assert _stem("rfp") == "rfp", "short words are left alone"
