"""The SQLite sink — now the primary destination. (docs/PLAN.md §0)

CLAUDE.md §4 said "the Sheet *is* the product". That is no longer true: the dashboard is,
and this sink is what feeds it. `sinks/sheets.py` survives unchanged as an *export*
target for the shortlist Mauri keeps, so the argument that mattered — she still ends up
owning her data in a tool she understands — survives the change.

Writing through the sink protocol rather than straight from the runner is what keeps
that possible. The agent still emits Opportunity records and knows nothing about where
they land.
"""

from __future__ import annotations

import logging

from agent.models import Opportunity, RunLog

from app import repo
from app.db import dumps, session

log = logging.getLogger(__name__)


class SqliteSink:
    """Upserts opportunities and the run log into data/rise.db."""

    name = "sqlite"

    def __init__(self, run_id: str | None = None, db_path=None) -> None:
        self.run_id = run_id
        self.db_path = db_path

    def write_opportunities(self, opportunities: list[Opportunity],
                            run: RunLog | None = None) -> int:
        with session(self.db_path) as conn:
            for opp in opportunities:
                repo.save_opportunity(conn, opp, run_id=self.run_id)
        return len(opportunities)

    def write_run_log(self, run: RunLog) -> None:
        d = run.to_dict()
        with session(self.db_path) as conn:
            if self.run_id is None or repo.get_run(conn, self.run_id) is None:
                self.run_id = repo.create_run(conn, self.run_id)
            repo.update_run(
                conn, self.run_id,
                finished_at=d["finished_at"],
                status="done" if d["stop_reason"] != "error" else "failed",
                stop_reason=d["stop_reason"],
                usd_spent=d["usd_spent"],
                sources_attempted=d["sources_attempted"],
                sources_ok=d["sources_ok"],
                sources_failed=d["sources_failed"],
                candidates_parsed=d["candidates_parsed"],
                rejected_by_filter=dumps(d["rejected_by_filter"]),
                opportunities_scored=d["opportunities_scored"],
                opportunities_not_stated=d["opportunities_not_stated"],
                purged_rows=getattr(run, "purged_rows", 0),
                duplicates_skipped=getattr(run, "duplicates_skipped", 0),
                notes=dumps(d["notes"]),
                source_health=dumps(d.get("source_health") or []),
            )
