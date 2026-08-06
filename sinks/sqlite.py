"""The SQLite sink — now the primary destination. (CLAUDE.md)

CLAUDE.md said "the Sheet *is* the product". That is no longer true: the dashboard is,
and this sink is what feeds it. `sinks/sheets.py` survives unchanged as an *export*
target for the shortlist the user keeps, so the argument that mattered — they still end up
owning their data in a tool they understand — survives the change.

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

    def __init__(self, run_id: str | None = None, db_path=None,
                 org_id: str | None = None) -> None:
        self.run_id = run_id
        self.db_path = db_path
        # Whose findings these are. Without it every org's results landed in one pile
        # keyed only by (source_url, title), so two nonprofits looking at the same grant
        # page overwrote each other's row.
        from app.db import DEFAULT_ORG_ID
        self.org_id = org_id or DEFAULT_ORG_ID

    def _ready(self) -> None:
        """Make sure the schema exists before writing.

        The pipeline runs for minutes and the sink is the last thing it does, so the
        database it opens at the end is not necessarily the one it read config from at
        the start — it can be deleted, restored from a backup, or moved in between.
        Without this, a whole scored run's results are lost at the final step to a
        `no such table` error, which is the most expensive possible moment to fail.
        (Learned the hard way: the file was deleted mid-run.)
        """
        from app.db import init_db

        init_db(self.db_path, seed=False)

    def write_opportunities(self, opportunities: list[Opportunity],
                            run: RunLog | None = None) -> int:
        self._ready()
        with session(self.db_path) as conn:
            for opp in opportunities:
                repo.save_opportunity(conn, opp, run_id=self.run_id,
                                      org_id=self.org_id)
        return len(opportunities)

    def write_run_log(self, run: RunLog) -> None:
        self._ready()
        d = run.to_dict()
        with session(self.db_path) as conn:
            if self.run_id is None or repo.get_run(conn, self.run_id) is None:
                self.run_id = repo.create_run(conn, self.run_id, org_id=self.org_id)
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
                rejects=dumps(d.get("rejects") or []),
                triaged=d.get("triaged", 0),
                scored=d.get("scored", 0),
                usd_by_stage=dumps(d.get("usd_by_stage") or {}),
                opportunities_scored=d["opportunities_scored"],
                opportunities_not_stated=d["opportunities_not_stated"],
                purged_rows=getattr(run, "purged_rows", 0),
                duplicates_skipped=getattr(run, "duplicates_skipped", 0),
                notes=dumps(d["notes"]),
                source_health=dumps(d.get("source_health") or []),
            )
