"""The seam for finding funders outside the organization's partner list.

the user asked for two things that pull in opposite directions: search the funders the org
already knows first, *and* go looking for new ones — government RFPs and contracts
included (§11 Q3, answered: yes).

The first half is the existing crawl over the funders table. The second half is being
built on a separate branch, so what lives here is the interface it plugs into and a
null implementation that does nothing. That is deliberate:

  - the dashboard's "search beyond our partners" checkbox can ship and be wired up now,
    and it honestly reports that no provider is installed rather than silently doing
    nothing;
  - when the discovery branch merges, it adds one class here and one line in the
    registry below. No pipeline code changes, and there is no merge conflict in
    fetch.py, parse.py, filters.py, or sources.py.

A provider's job is narrow: given the program cards the user ticked, return `Source`
records pointing at pages worth fetching. It does not fetch, parse, filter, or score —
everything downstream of it is the pipeline that already exists, including the §6
accuracy gate. A discovered source gets exactly the same scrutiny as a warm one.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from .config import ProgramCard
from .sources import Source

log = logging.getLogger(__name__)


@runtime_checkable
class DiscoveryProvider(Protocol):
    """Finds candidate sources beyond the partner list."""

    name: str

    def discover(self, programs: list[ProgramCard], *,
                 sectors: list[str], limit: int) -> list[Source]:
        """Return candidate sources. Must not fetch, score, or spend past `limit`."""
        ...


class NullDiscovery:
    """The default: finds nothing, and says so.

    Not a stub that pretends to work. A run with "search beyond our partners" ticked
    and no provider installed reports `discovery_provider: none` in its notes, so the
    difference between "we looked and found nothing" and "nothing looked" is visible in
    the run log instead of being indistinguishable.
    """

    name = "none"

    def discover(self, programs: list[ProgramCard], *,
                 sectors: list[str], limit: int) -> list[Source]:
        log.info("Discovery: no provider installed — searching the partner list only.")
        return []


_REGISTRY: dict[str, DiscoveryProvider] = {}


def register(provider: DiscoveryProvider) -> None:
    """Called by a provider module at import time. One line to land a new one."""
    _REGISTRY[provider.name] = provider
    log.debug("registered discovery provider %r", provider.name)


def get_provider(name: str | None = None) -> DiscoveryProvider:
    """The provider to use this run. Falls back to NullDiscovery, never to an error —
    a missing provider must degrade the run, not fail it."""
    if name and name in _REGISTRY:
        return _REGISTRY[name]
    for provider in _REGISTRY.values():
        return provider
    return NullDiscovery()


def available() -> list[str]:
    return sorted(_REGISTRY) or ["none"]
