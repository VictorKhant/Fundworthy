"""The fetcher's retry loop: politeness under real conditions, not just the happy path.

Offline by construction, same shape as tests/test_urlguard.py — DNS is stubbed and
`httpx.AsyncClient.request` is monkeypatched, so nothing here opens a socket.

FUTURE.md P1: `Fetcher.get()`'s retry loop used to call `_send(method, url)` again on
every retry, and `_send` always walks its redirect chain from scratch — so a 429/503 on
the final hop of a two-redirect page turned "two retries" into up to nine real requests,
worst exactly when the host has just said it is overloaded. These tests assert on the
actual number and target of the underlying HTTP calls, not just the final result, because
that is the one thing a naive fix (right FetchResult, same request count) would not catch.

    .venv/bin/python -m pytest tests/test_fetch.py -q
"""

from __future__ import annotations

import asyncio
import functools
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.fetch import Fetcher, MAX_RETRIES  # noqa: E402


def sync(fn):
    """Run an async test without pulling in a pytest plugin — same helper as
    test_urlguard.py; not worth a shared module for one decorator."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@pytest.fixture()
def dns(monkeypatch):
    """Resolve names from a table instead of the network."""
    table: dict[str, list[str]] = {}

    def fake_getaddrinfo(host, port, *a, **kw):
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 (addr, port)) for addr in table[host]]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return table


@pytest.fixture(autouse=True)
def _no_real_delay(monkeypatch):
    """The backoff sleeps are real seconds otherwise — patch them out so this suite
    stays fast, the same way the retry logic itself is the thing under test, not the
    timing."""
    async def instant_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


@sync
async def test_a_429_retry_resumes_from_the_last_hop_not_the_original_url(dns, monkeypatch):
    """The bug, directly. A redirects to B; B returns 429 once, then 200. Before the
    fix, the retry re-requested A (to re-derive the redirect to B) before ever reaching
    B again — two calls per attempt, four total. The fix resumes straight at B on the
    retry — three calls total, and A is only ever requested once."""
    dns["a.example.com"] = ["93.184.216.34"]
    dns["b.example.com"] = ["93.184.216.35"]
    calls: list[str] = []
    b_attempts = 0

    async def fake_request(self, method, url, **kwargs):
        nonlocal b_attempts
        calls.append(str(url))
        request = httpx.Request(method, url)
        if "a.example.com" in str(url):
            return httpx.Response(
                302, headers={"location": "https://b.example.com/g"}, request=request)
        b_attempts += 1
        if b_attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, text="<html>ok</html>",
                              headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://a.example.com/g")

    assert result.ok
    assert calls.count("https://a.example.com/g") == 1, (
        f"A was requested {calls.count('https://a.example.com/g')} times — "
        "the retry re-walked the redirect instead of resuming at B"
    )
    assert calls == [
        "https://a.example.com/g", "https://b.example.com/g", "https://b.example.com/g",
    ]


@sync
async def test_a_timeout_mid_chain_retry_resumes_at_the_hop_that_timed_out(dns, monkeypatch):
    """Same fix, the network-failure path: B times out instead of returning 429. A must
    still only be requested once — the exception path resumes exactly like the status-
    code path does."""
    dns["a.example.com"] = ["93.184.216.34"]
    dns["b.example.com"] = ["93.184.216.35"]
    calls: list[str] = []
    b_attempts = 0

    async def fake_request(self, method, url, **kwargs):
        nonlocal b_attempts
        calls.append(str(url))
        request = httpx.Request(method, url)
        if "a.example.com" in str(url):
            return httpx.Response(
                301, headers={"location": "https://b.example.com/g"}, request=request)
        b_attempts += 1
        if b_attempts == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, text="<html>ok</html>",
                              headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://a.example.com/g")

    assert result.ok
    assert calls.count("https://a.example.com/g") == 1


@sync
async def test_giving_up_still_reports_the_original_url_not_the_last_hop(dns, monkeypatch):
    """Resuming internally must not leak into what the caller sees — a FetchResult for
    a source that never worked still names the URL it was asked to fetch."""
    dns["a.example.com"] = ["93.184.216.34"]
    dns["b.example.com"] = ["93.184.216.35"]

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        if "a.example.com" in str(url):
            return httpx.Response(
                302, headers={"location": "https://b.example.com/g"}, request=request)
        return httpx.Response(503, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://a.example.com/g")

    assert not result.ok
    assert result.url == "https://a.example.com/g"
    assert result.error == "http_503"


@sync
async def test_fetch_json_post_redirect_downgrade_survives_a_retry(dns, monkeypatch):
    """agent/apis.py calls fetch_json with method="POST" against Grants.gov. A 303 (or a
    301/302 on a POST) downgrades to a bodyless GET partway through the chain — and a
    retry that resumes at that hop has to remember it is now a GET, or it replays a
    write with a body against a URL the origin already told us takes neither."""
    dns["search.example.com"] = ["93.184.216.34"]
    dns["results.example.com"] = ["93.184.216.35"]
    calls: list[tuple[str, str, bool]] = []  # (method, url, had_json_body)
    result_attempts = 0

    async def fake_request(self, method, url, **kwargs):
        nonlocal result_attempts
        calls.append((method, str(url), kwargs.get("json") is not None))
        request = httpx.Request(method, url)
        if "search.example.com" in str(url):
            # 303: any method becomes GET with no body from here on.
            return httpx.Response(
                303, headers={"location": "https://results.example.com/r"}, request=request)
        result_attempts += 1
        if result_attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, json={"hits": []}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        payload, error = await f.fetch_json(
            "https://search.example.com/q", method="POST", json_body={"keyword": "x"})

    assert error is None
    assert payload == {"hits": []}
    assert calls == [
        ("POST", "https://search.example.com/q", True),
        ("GET", "https://results.example.com/r", False),
        ("GET", "https://results.example.com/r", False),
    ], calls


@sync
async def test_a_second_hop_getting_its_own_redirect_on_retry_is_still_followed(
        dns, monkeypatch):
    """Resuming at the last hop does not mean resuming with `_send`'s redirect handling
    switched off — if that hop itself now points somewhere else, the retry still has to
    follow it."""
    dns["a.example.com"] = ["93.184.216.34"]
    dns["b.example.com"] = ["93.184.216.35"]
    dns["c.example.com"] = ["93.184.216.36"]
    calls: list[str] = []
    b_attempts = 0

    async def fake_request(self, method, url, **kwargs):
        nonlocal b_attempts
        calls.append(str(url))
        request = httpx.Request(method, url)
        if "a.example.com" in str(url):
            return httpx.Response(
                302, headers={"location": "https://b.example.com/g"}, request=request)
        if "b.example.com" in str(url):
            b_attempts += 1
            if b_attempts == 1:
                return httpx.Response(429, request=request)
            # On retry, B itself now redirects to C.
            return httpx.Response(
                302, headers={"location": "https://c.example.com/g"}, request=request)
        return httpx.Response(200, text="<html>ok</html>",
                              headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://a.example.com/g")

    assert result.ok
    assert result.final_url == "https://c.example.com/g"
    assert calls.count("https://a.example.com/g") == 1


@sync
async def test_retries_are_still_bounded(dns, monkeypatch):
    """The resume optimization must not turn a bounded retry loop into an unbounded
    one — a host that always says 429 still gives up after MAX_RETRIES."""
    dns["always-busy.example.com"] = ["93.184.216.34"]
    attempts = 0

    async def fake_request(self, method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://always-busy.example.com/g")

    assert not result.ok
    assert attempts == MAX_RETRIES + 1
