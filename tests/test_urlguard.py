"""SSRF: the fetcher must only ever reach public addresses.

The app fetches URLs a signed-in user types — the "build a card from a link" assistant,
and a funder's URL on the Funders page. Bound to 127.0.0.1 that was harmless. On a public
VM it lets the caller aim the server at anything the server can reach, and hands the
response back to them through the assistant's draft.

The two targets that matter on this deployment:

    169.254.169.254   cloud instance metadata, answers unauthenticated
    127.0.0.1:8000    Fundworthy itself, behind nginx

Offline by construction: DNS is stubbed, and nothing here opens a socket.
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

from agent.fetch import Fetcher                              # noqa: E402
from agent.urlguard import (BlockedURL, address_block_reason,  # noqa: E402
                            ensure_public_url)


def sync(fn):
    """Run an async test without pulling in a pytest plugin.

    The suite has no async tests today and no pytest-asyncio, and this is not worth a new
    dependency in requirements.txt for a handful of coroutines.
    """
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


# --- the address classifier ---------------------------------------------------

@pytest.mark.parametrize("address, expected", [
    ("169.254.169.254", "link-local"),   # cloud metadata — the one that matters most
    ("127.0.0.1", "loopback"),
    ("10.0.0.5", "private"),
    ("172.16.4.4", "private"),
    ("192.168.1.1", "private"),
    ("0.0.0.0", "private"),   # 0.0.0.0/8 counts as private before it counts as unspecified
    ("100.64.0.1", "in 100.64.0.0/10"),  # carrier-grade NAT
    ("224.0.0.1", "multicast"),
    ("::1", "loopback"),
    ("fd00:ec2::254", "private"),        # IPv6 metadata / unique-local
])
def test_private_addresses_are_named_and_refused(address, expected):
    assert address_block_reason(address) == expected


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"])
def test_ordinary_public_addresses_are_allowed(address):
    assert address_block_reason(address) is None


def test_an_ipv4_address_wearing_an_ipv6_hat_is_still_loopback():
    """`IPv6Address('::ffff:127.0.0.1').is_loopback` is False, which is the sort of
    detail an allow-list is quietly wrong about for a year."""
    assert address_block_reason("::ffff:127.0.0.1") == "loopback"
    assert address_block_reason("::ffff:169.254.169.254") == "link-local"


# --- ensure_public_url --------------------------------------------------------

@sync
async def test_the_metadata_service_is_refused_by_ip(dns):
    with pytest.raises(BlockedURL, match="link-local"):
        await ensure_public_url("http://169.254.169.254/opc/v2/instance/")


@sync
async def test_localhost_is_refused_even_though_it_needs_dns(dns):
    dns["localhost"] = ["127.0.0.1"]
    with pytest.raises(BlockedURL, match="loopback"):
        await ensure_public_url("http://localhost:8000/api/state")


@sync
async def test_a_hostname_that_resolves_inward_is_refused(dns):
    """The interesting case: nothing about the URL looks wrong. An attacker controls a
    public domain and points it at the metadata address."""
    dns["evil.example.com"] = ["169.254.169.254"]
    with pytest.raises(BlockedURL, match="link-local"):
        await ensure_public_url("https://evil.example.com/")


@sync
async def test_one_bad_answer_among_several_is_enough_to_refuse(dns):
    """A name with both a public and a private A record would otherwise be a coin flip,
    and one side of that coin is the metadata service."""
    dns["mixed.example.com"] = ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(BlockedURL, match="loopback"):
        await ensure_public_url("https://mixed.example.com/")


@sync
async def test_a_real_funder_url_still_passes(dns):
    dns["www.sandiegofoundation.org"] = ["93.184.216.34"]
    await ensure_public_url("https://www.sandiegofoundation.org/grants/")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://example.com/",
    "ftp://example.com/",
])
@sync
async def test_only_http_and_https_are_fetchable(dns, url):
    with pytest.raises(BlockedURL):
        await ensure_public_url(url)


# --- the fetcher --------------------------------------------------------------

@sync
async def test_get_refuses_a_private_url_without_opening_a_socket(dns):
    """`get` returns a FetchResult rather than raising: a blocked URL is one bad source,
    not a reason to end a crawl."""
    async with Fetcher() as f:
        result = await f.get("http://169.254.169.254/opc/v2/instance/")

    assert not result.ok
    assert result.error.startswith("blocked_url")
    assert "link-local" in result.error


@sync
async def test_a_redirect_into_the_metadata_service_is_not_followed(dns, monkeypatch):
    """The hole the scheme check could never have caught. The URL is a perfectly ordinary
    public page; the *redirect* is the attack, and httpx's own redirect following meant we
    fetched it and handed back the body."""
    dns["public.example.com"] = ["93.184.216.34"]
    seen: list[str] = []

    async def fake_request(self, method, url, **kwargs):
        seen.append(str(url))
        request = httpx.Request(method, url)
        if "public.example.com" in str(url):
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/opc/v2/instance/"},
                request=request)
        return httpx.Response(200, text="SECRET INSTANCE METADATA", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://public.example.com/grants")

    assert not result.ok
    assert result.error.startswith("blocked_redirect")
    assert not any("169.254" in u for u in seen), \
        "the metadata service was contacted despite the guard"


@sync
async def test_an_ordinary_redirect_is_still_followed(dns, monkeypatch):
    """The guard must not break the crawler: funder sites redirect constantly."""
    dns["old.example.com"] = ["93.184.216.34"]
    dns["new.example.com"] = ["93.184.216.35"]

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        if "old.example.com" in str(url):
            return httpx.Response(301, headers={"location": "https://new.example.com/g"},
                                  request=request)
        return httpx.Response(200, text="<html><body>Grant page</body></html>",
                              headers={"content-type": "text/html"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://old.example.com/g")

    assert result.ok
    assert "Grant page" in result.html
    assert result.final_url == "https://new.example.com/g"


@sync
async def test_a_redirect_loop_gives_up(dns, monkeypatch):
    dns["loop.example.com"] = ["93.184.216.34"]

    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(302, headers={"location": "https://loop.example.com/next"},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    async with Fetcher(respect_robots=False) as f:
        result = await f.get("https://loop.example.com/start")
    assert not result.ok


@sync
async def test_fetch_json_is_guarded_too(dns):
    """The API adapters hit known endpoints, but they take their URLs from the funders
    table, which the user edits."""
    async with Fetcher() as f:
        payload, error = await f.fetch_json("http://127.0.0.1:8000/api/state")
    assert payload is None
    assert error.startswith("blocked_url")


# --- the assistant, which is the reachable entry point ------------------------

@sync
async def test_the_assistant_explains_itself_without_leaking_internals(dns):
    from app.assistant import AssistantError, fetch_page_text

    with pytest.raises(AssistantError) as caught:
        await fetch_page_text("http://169.254.169.254/opc/v2/instance/")

    message = str(caught.value)
    assert "public website" in message
    # No jargon, no address, nothing that reads as a hint about what to try next.
    for leak in ("link-local", "169.254", "blocked_url", "resolves"):
        assert leak not in message
