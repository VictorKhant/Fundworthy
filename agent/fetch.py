"""Fetching: httpx + retry + politeness delays. (CLAUDE.md)

We are a small nonprofit's agent hitting funders' own websites once a week. Behave
accordingly: identify ourselves honestly, obey robots.txt, one request at a time per
host, and back off rather than hammer. A funder blocking our IP would be a real
cost to the nonprofits that rely on this.
"""

from __future__ import annotations

import asyncio
import re
import logging
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from .urlguard import BlockedURL, ensure_public_url

log = logging.getLogger(__name__)

USER_AGENT = (
    "Fundworthy/0.1 "
    "(+https://github.com/VictorKhant/Fundworthy; nonprofit grant research)"
)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_RETRIES = 2
PER_HOST_DELAY_SECONDS = 2.0
MAX_BYTES = 3_000_000  # a grants page over 3MB is not a grants page
MAX_REDIRECTS = 5      # httpx's own default is 20; a grants page needs nowhere near it
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

# Content types we can actually read. Anything else — PDF above all — decodes into
# noise that looks like text to everything downstream.
_READABLE_TYPE = re.compile(r"^(text/|application/(xhtml\+xml|xml|json))", re.IGNORECASE)


@dataclass
class FetchResult:
    url: str
    status: int | None
    html: str | None
    error: str | None = None
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and bool(self.html)


class Fetcher:
    """Async fetcher with per-host serialization and robots.txt caching."""

    def __init__(self, *, respect_robots: bool = True) -> None:
        self.respect_robots = respect_robots
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "Fetcher":
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=REQUEST_TIMEOUT,
            # Redirects are followed by `_send`, one hop at a time, so that every hop can
            # be checked against `urlguard` before we connect to it. With httpx doing it
            # for us, a public URL redirecting to 169.254.169.254 was fetched and the
            # body handed back — the redirect being exactly the part we never inspected.
            follow_redirects=False,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    def _lock_for(self, host: str) -> asyncio.Lock:
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Lock()
        return self._host_locks[host]

    async def _send(self, method: str, url: str, *,
                    on_hop: Callable[[str, str], None] | None = None,
                    **kwargs) -> httpx.Response:
        """One request, following redirects ourselves so every hop is checked.

        Raises `BlockedURL` if the starting URL — or anywhere a redirect points — is not
        a public address. Everything else propagates unchanged, so the retry and
        error-handling in the callers keeps working exactly as before.

        `on_hop`, if given, is called with `(url, method)` right before each hop is
        requested — including the first hop. This is what lets a caller's retry loop
        resume from the last hop actually reached instead of re-walking the whole chain;
        see `get()`. Called whether that hop succeeds, redirects, or the request itself
        raises, since a retry after a timeout should resume at the hop that timed out,
        not the one before it. The method matters as well as the URL: a 303 (or a
        301/302 on a POST) downgrades to GET partway through a chain, and a retry that
        resumes at that hop has to resume with the downgraded method too, not the
        original POST.
        """
        assert self._client is not None
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            if on_hop:
                on_hop(current, method)
            await ensure_public_url(current)
            resp = await self._client.request(method, current, **kwargs)
            if resp.status_code not in _REDIRECT_CODES:
                return resp

            location = resp.headers.get("location")
            if not location:
                return resp                      # a 30x with nowhere to go is just a 30x

            # Resolved here rather than read off `resp.next_request`, which only exists
            # when httpx's own redirect machinery ran. Doing it ourselves also handles
            # the common relative form (`Location: /grants/`) and keeps the next URL
            # something we derived, not something httpx handed us.
            nxt = urljoin(current, location)

            # 303, and 301/302 on a POST, become GET with no body — the same rule httpx
            # applies. Keeping it means switching method and dropping the payload rather
            # than replaying a write against a URL the origin chose.
            if resp.status_code == 303 or (
                    resp.status_code in (301, 302) and method.upper() == "POST"):
                method = "GET"
                kwargs.pop("json", None)
                kwargs.pop("content", None)
                kwargs.pop("data", None)
            log.debug("redirect %s -> %s", current, nxt)
            current = nxt

        raise httpx.TooManyRedirects(
            f"more than {MAX_REDIRECTS} redirects starting at {url}",
            request=httpx.Request(method, url))

    async def _allowed(self, url: str) -> bool:
        """robots.txt check. A robots.txt we cannot read is treated as permissive —
        that is the conventional reading, and these are public grant pages."""
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            rp: urllib.robotparser.RobotFileParser | None = None
            try:
                assert self._client is not None
                resp = await self._send("GET", f"{origin}/robots.txt", timeout=10.0)
                if resp.status_code == 200:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(resp.text.splitlines())
            except Exception as exc:  # noqa: BLE001 — absence of robots is not an error
                log.debug("robots.txt unavailable for %s: %s", origin, exc)
            self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    async def get(self, url: str) -> FetchResult:
        assert self._client is not None, "use `async with Fetcher() as f`"
        host = urlparse(url).netloc

        # Before robots.txt, because fetching robots.txt is itself a request to the host
        # and a blocked address should not get even that.
        try:
            await ensure_public_url(url)
        except BlockedURL as exc:
            log.warning("refusing to fetch %s: %s", url, exc)
            return FetchResult(url=url, status=None, html=None,
                               error=f"blocked_url: {exc}")

        if not await self._allowed(url):
            log.info("robots.txt disallows %s — skipping", url)
            return FetchResult(url=url, status=None, html=None, error="robots_disallowed")

        async with self._lock_for(host):
            last_error: str | None = None
            # Where the NEXT attempt should start — the original URL on the first try,
            # then whichever hop the previous attempt actually reached. Before this,
            # every retry called `_send("GET", url)` again, so `_send`'s own redirect
            # walk restarted from hop zero every time: a 429/503 on the final hop of a
            # two-redirect page turned "two retries" into up to nine real requests —
            # worst exactly when the host has just said it's overloaded. `on_hop` below
            # updates this to the last URL `_send` actually requested, whether that hop
            # succeeded, redirected, or raised, so a retry resumes there instead.
            resume_from = url

            def _track(hop_url: str, _method: str) -> None:
                nonlocal resume_from
                resume_from = hop_url

            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await self._send("GET", resume_from, on_hop=_track)

                    # Back off on rate limits and server errors; give up on 4xx.
                    if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
                        wait = PER_HOST_DELAY_SECONDS * (2 ** attempt)
                        log.info("%s returned %s — backing off %.1fs", url, resp.status_code, wait)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code >= 400:
                        return FetchResult(
                            url=url,
                            status=resp.status_code,
                            html=None,
                            error=f"http_{resp.status_code}",
                            final_url=str(resp.url),
                        )

                    # A URL with no extension can still serve a PDF, and decoding one
                    # as text yields its raw byte stream — which the parser will
                    # happily hand to a model that scores it. The extension check in
                    # parse.py catches most of these; this catches the rest, at the
                    # only point where the server has told us what it actually sent.
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                    if ctype and not _READABLE_TYPE.match(ctype):
                        return FetchResult(
                            url=url, status=resp.status_code, html=None,
                            error=f"unreadable_content_type:{ctype}",
                            final_url=str(resp.url),
                        )

                    content = resp.text
                    if len(resp.content) > MAX_BYTES:
                        content = resp.text[:MAX_BYTES]
                    return FetchResult(
                        url=url,
                        status=resp.status_code,
                        html=content,
                        final_url=str(resp.url),
                    )

                except BlockedURL as exc:
                    # A redirect pointed somewhere private. Not retryable, and not the
                    # host's fault — stop here rather than spending two more attempts.
                    log.warning("refusing to follow a redirect from %s: %s", url, exc)
                    return FetchResult(url=url, status=None, html=None,
                                       error=f"blocked_redirect: {exc}")
                except httpx.TooManyRedirects:
                    # Not a TransportError, so without this it escapes the retry loop and
                    # takes the whole crawl down. A funder with a redirect loop is one
                    # unhealthy source, which is a thing the run log already knows how to
                    # say.
                    log.info("%s exceeded %d redirects — giving up", url, MAX_REDIRECTS)
                    return FetchResult(url=url, status=None, html=None,
                                       error="too_many_redirects")
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(PER_HOST_DELAY_SECONDS * (2 ** attempt))
                        continue

            return FetchResult(url=url, status=None, html=None, error=last_error or "unknown")

    async def fetch_json(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> tuple[dict | list | None, str | None]:
        """One request against a JSON API. Returns (payload, error).

        Deliberately not routed through get(): these are published programmatic
        endpoints, so there is no robots.txt question and no HTML to size-cap. The
        per-host lock still applies — politeness is not conditional on the format.

        Never raises. A broken API returns (None, reason) so the caller can record
        it as one unhealthy source and carry on with the others.
        """
        assert self._client is not None, "use `async with Fetcher() as f`"
        host = urlparse(url).netloc

        async with self._lock_for(host):
            last_error: str | None = None
            resume_from = url        # see the matching comment in get()
            resume_method = method

            def _track(hop_url: str, hop_method: str) -> None:
                nonlocal resume_from, resume_method
                resume_from = hop_url
                resume_method = hop_method

            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await self._send(
                        resume_method,
                        resume_from,
                        params=params,
                        # `resume_method` can differ from the caller's own `method` on a
                        # retry — a 303 (or a 301/302 on a POST) downgrades to GET
                        # partway through a chain, and a GET carries no body. Resending
                        # `json_body` against a now-GET hop would attach a write payload
                        # to a request the origin already told us has none.
                        json=json_body if resume_method != "GET" else None,
                        headers={"Accept": "application/json"},
                        on_hop=_track,
                    )
                    if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
                        await asyncio.sleep(PER_HOST_DELAY_SECONDS * (2 ** attempt))
                        continue
                    if resp.status_code >= 400:
                        return None, f"http_{resp.status_code}"
                    return resp.json(), None
                except BlockedURL as exc:
                    log.warning("refusing to fetch %s: %s", url, exc)
                    return None, f"blocked_url: {exc}"
                except httpx.TooManyRedirects:
                    return None, "too_many_redirects"
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(PER_HOST_DELAY_SECONDS * (2 ** attempt))
                        continue
                except ValueError as exc:  # JSON decode — the endpoint changed shape
                    return None, f"bad_json: {exc}"

            return None, last_error or "unknown"

    async def get_many(self, urls: list[str]) -> list[FetchResult]:
        """Concurrent across hosts, serialized within a host by the per-host lock."""
        results = await asyncio.gather(*(self.get(u) for u in urls), return_exceptions=True)
        out: list[FetchResult] = []
        for url, res in zip(urls, results):
            if isinstance(res, BaseException):
                out.append(FetchResult(url=url, status=None, html=None, error=repr(res)))
            else:
                out.append(res)
            await asyncio.sleep(0)  # yield; politeness spacing lives in the host lock
        return out
