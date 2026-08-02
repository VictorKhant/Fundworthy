"""Local JSONL sink. No credentials, no network.

Exists so Block 1 is runnable and reviewable before anyone shares the Sheet, and so
every run leaves an artifact on disk for the evidence package. The Sheet is the
product; this is the receipt.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.models import Opportunity, RunLog

from .base import split_sections


class JsonlSink:
    name = "jsonl"

    def __init__(self, out_dir: str | Path = "out") -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    def write_opportunities(
        self, opportunities: list[Opportunity], run: RunLog | None = None
    ) -> int:
        scored, not_stated = split_sections(opportunities)
        path = self.out_dir / f"opportunities-{self.stamp}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for opp in scored + not_stated:
                fh.write(json.dumps(opp.to_dict(), ensure_ascii=False) + "\n")
        return len(scored) + len(not_stated)

    def write_run_log(self, run: RunLog) -> None:
        path = self.out_dir / f"run-{self.stamp}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
