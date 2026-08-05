"""Where the fetcher is allowed to point.

The agent fetches URLs on behalf of a signed-in user. Two of those URLs are typed by a
person: the one pasted into the "build a program card from a link" assistant
(`app/assistant.py`), and a funder's URL added on the Funders page. On a laptop bound to
127.0.0.1 that was fine — the only machine reachable was your own. On a public VM it is a
**server-side request forgery** primitive: the caller chooses an address, the server
connects to it from inside the network, and the assistant summarises whatever comes back
into a card handed straight to the caller.

The prize on a cloud VM is the instance metadata service at `169.254.169.254`, which
answers unauthenticated to anything that can reach it. On Oracle it will serve instance
details and, depending on configuration, credentials. `127.0.0.1:8000` is also worth
having: that is Fundworthy itself, behind nginx, where "requests from localhost" is a
category the app has never had to think about.

So: every URL the fetcher touches resolves to a **public** address, and that is checked
per hop rather than once, because a redirect is a second URL that the first one chose.

**What this does not do.** The check resolves a hostname and then httpx resolves it again
to connect. A name that answers with a public address on the first lookup and a private
one on the second — DNS rebinding — slips through the gap. Closing it properly means
pinning the connection to the address we validated, which is a custom transport and a
different piece of work. This blocks every direct attempt and every redirect chain, which
is the whole of the realistic risk here; the residual is written down rather than papered
over.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

log = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ranges `ipaddress`'s own predicates miss or classify in a way that does not suit us.
# Carrier-grade NAT is the notable one: reachable from a cloud host, not a funder's
# website, and only counted as private by `is_private` on newer Pythons.
EXTRA_BLOCKED = (
    ipaddress.ip_network("100.64.0.0/10"),    # RFC 6598 carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),     # IETF protocol assignments
    ipaddress.ip_network("::/128"),           # unspecified, v6
)


class BlockedURL(ValueError):
    """The URL is syntactically fine and we are still not fetching it."""


def _unwrap(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """`::ffff:127.0.0.1` is loopback wearing a v6 hat, and none of IPv6Address's
    predicates say so — `.is_loopback` on it is False. Unwrap before judging."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return mapped
    # 6to4 and Teredo embed a v4 address too; only the widely-used ones are worth
    # unwrapping, and `sixtofour`/`teredo` are both None on ordinary addresses.
    for attr in ("sixtofour", "teredo"):
        embedded = getattr(ip, attr, None)
        if embedded is not None:
            return embedded[0] if isinstance(embedded, tuple) else embedded
    return ip


def address_block_reason(raw: str) -> str | None:
    """Why this IP is off limits, or None if it is a fine public address."""
    try:
        ip = _unwrap(ipaddress.ip_address(raw))
    except ValueError:
        return "not an IP address"

    for name in ("is_loopback", "is_link_local", "is_private", "is_reserved",
                 "is_multicast", "is_unspecified"):
        if getattr(ip, name, False):
            # link-local before private in the message: 169.254.169.254 is both, and
            # "link-local" is the one that tells a reader what was actually being tried.
            return name.removeprefix("is_").replace("_", "-")

    for net in EXTRA_BLOCKED:
        if ip.version == net.version and ip in net:
            return f"in {net}"
    return None


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


async def ensure_public_url(url: str) -> None:
    """Raise `BlockedURL` unless every address `url` resolves to is public.

    Every address, not the first: a name with both a public and a private A record would
    otherwise be a coin flip, and one side of that coin is the metadata service.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(
            f"{parsed.scheme or 'that'} is not a scheme we fetch — use http or https.")

    host = parsed.hostname
    if not host:
        raise BlockedURL("that link has no hostname in it.")

    # A bare IP needs no DNS, and must not get a free pass by skipping the check.
    literal = address_block_reason(host)
    if literal is not None and literal != "not an IP address":
        raise BlockedURL(f"{host} is a {literal} address — that is not a public website.")

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = await asyncio.to_thread(_resolve, host, port)
    except socket.gaierror as exc:
        raise BlockedURL(f"could not look up {host} ({exc.strerror or exc}).") from exc

    if not addresses:
        raise BlockedURL(f"{host} does not resolve to anything.")

    for address in addresses:
        reason = address_block_reason(address)
        if reason is not None:
            log.warning("refused to fetch %s — %s resolves to %s (%s)",
                        url, host, address, reason)
            raise BlockedURL(
                f"{host} resolves to {address}, which is a {reason} address. "
                "Fundworthy only fetches public websites.")
