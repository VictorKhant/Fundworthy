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
