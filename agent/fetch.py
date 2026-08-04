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
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Fundworthy/0.1 "
    "(+https://github.com/VictorKhant/Rise-Fund-Finder; nonprofit grant research)"
)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_RETRIES = 2
PER_HOST_DELAY_SECONDS = 2.0
MAX_BYTES = 3_000_000  # a grants page over 3MB is not a grants page

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
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    def _lock_for(self, host: str) -> asyncio.Lock:
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Lock()
        return self._host_locks[host]

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
                resp = await self._client.get(f"{origin}/robots.txt", timeout=10.0)
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

        if not await self._allowed(url):
            log.info("robots.txt disallows %s — skipping", url)
            return FetchResult(url=url, status=None, html=None, error="robots_disallowed")

        async with self._lock_for(host):
            last_error: str | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await self._client.get(url)

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
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await self._client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers={"Accept": "application/json"},
                    )
                    if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
                        await asyncio.sleep(PER_HOST_DELAY_SECONDS * (2 ** attempt))
                        continue
                    if resp.status_code >= 400:
                        return None, f"http_{resp.status_code}"
                    return resp.json(), None
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
