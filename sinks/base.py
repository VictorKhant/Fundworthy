"""The Sink protocol. (CLAUDE.md §6)

The agent emits Opportunity records; sinks render them. Adding a non-Sheets
destination later means writing one file in here, not touching the agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent.models import Opportunity, RunLog


@runtime_checkable
class Sink(Protocol):
    name: str

    def write_opportunities(self, opportunities: list[Opportunity]) -> int:
        """Render the ranked list. Returns the number of records written."""
        ...

    def write_run_log(self, run: RunLog) -> None:
        """Append one row to the run log: cost, counts, stop reason."""
        ...


def split_sections(opportunities: list[Opportunity]) -> tuple[list[Opportunity], list[Opportunity]]:
    """Scored rows first (ranked), then rows whose award amount was never stated.

    Two blocks rather than one list because an unscored row has no score to be ranked
    by — dropping it loses real opportunities, and interleaving it invents a ranking.
    """
    from agent.models import Section

    scored = [o for o in opportunities if o.section is Section.SCORED]
    not_stated = [o for o in opportunities if o.section is Section.AMOUNT_NOT_STATED]
    scored.sort(key=lambda o: o.score, reverse=True)
    not_stated.sort(key=lambda o: (o.funder.casefold(), o.title.casefold()))
    return scored, not_stated
