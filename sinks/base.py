"""The Sink protocol. (CLAUDE.md)

The agent emits Opportunity records; sinks render them. Adding a non-Sheets
destination later means writing one file in here, not touching the agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent.models import Opportunity, RunLog


@runtime_checkable
class Sink(Protocol):
    name: str

    def write_opportunities(
        self, opportunities: list[Opportunity], run: RunLog | None = None
    ) -> int:
        """Render the ranked list. Returns the number of records written.

        `run` is optional so a sink can render coverage alongside the results. A short
        list means nothing on its own: it could be a quiet week or a broken source,
        and only the run log knows which.
        """
        ...

    def write_run_log(self, run: RunLog) -> None:
        """Append one row to the run log: cost, counts, stop reason."""
        ...


# --- coverage ----------------------------------------------------------------
#
# §9: no technical vocabulary on anything the user reads. "unreachable" and "http_503"
# are for the log; these sentences are for them.

_STATUS_PLAIN = {
    "unreachable": "could not be reached",
    "unparseable": "answered, but the page could not be read",
}


def coverage_banner(run: RunLog | None) -> list[str]:
    """Plain sentences describing what was and wasn't checked.

    This is the answer to "why is the list short this week?" — a question that
    otherwise costs the user a phone call, or worse, costs them trust in the list.

    Two separate things get said, because they mean different things. A source that
    broke is news and leads. A source with no address on file is a standing to-do
    that will read the same every week, so it goes last and it does not shout.
    """
    if run is None or not run.source_health:
        return []

    lines: list[str] = []
    checked, degraded = run.checked_sources, run.degraded_sources

    if degraded:
        detail = "; ".join(
            f"{h.funder} ({_STATUS_PLAIN.get(h.status.value, h.status.value)})"
            for h in degraded
        )
        n = len(degraded)
        lines.append(
            f"HEADS UP — {n} funding source{'' if n == 1 else 's'} could not be "
            f"checked this week, so this list may be incomplete: {detail}."
        )
        lines.append(
            f"The other {len(checked)} were checked normally, and everything below "
            "comes from those. If the same source fails week after week, that is worth "
            "reporting — it usually means a funder moved their page."
        )
    else:
        lines.append(
            f"All {len(checked)} funding sources were checked successfully this week."
        )

    unchecked = run.unchecked_sources
    if unchecked:
        names = ", ".join(h.funder for h in unchecked)
        lines.append(
            f"Still not being checked at all, because we have no application page on "
            f"file for them: {names}. If you know where they publish, that is the one "
            "thing that would widen this list."
        )
    return lines


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
