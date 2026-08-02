"""Normalized records. The agent emits these; sinks render them. (CLAUDE.md §6)

Accuracy rules enforced here rather than left to convention:
  - No source_url, no record. `Opportunity.__post_init__` refuses to build one.
  - A field we could not source stays None and sets needs_human_check.
    We never infer an amount or a deadline that was not on a page we fetched.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum


class Program(str, Enum):
    """RISE's three programs. Each lives in a different funder universe (§7)."""

    RULFP = "RULFP"            # RISE Urban Leadership Fellows
    RESILIENCE = "RESILIENCE"  # RISE Resilience & Renewal
    ARTS = "ARTS"              # RISE Arts


class Section(str, Enum):
    """Which block of the Sheet a record belongs in.

    Split exists because most funder pages never state an award amount. Rejecting
    those empties the pipeline; mixing them into the ranked list lets unscored rows
    compete with scored ones on a score they don't have. So they get their own block.
    """

    SCORED = "scored"                 # award amount sourced, ranked by score
    AMOUNT_NOT_STATED = "not_stated"  # no amount on the page — needs a human look


def stable_id(source_url: str, title: str) -> str:
    """Stable hash of source_url + title (§6). Same page + title => same id across runs,
    so re-runs update rather than duplicate."""
    payload = f"{source_url.strip().rstrip('/')}|{title.strip().casefold()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class RawCandidate:
    """Pre-normalization. What parse.py produces before filters or scoring run.

    Kept separate from Opportunity so that a page we could not make sense of is
    still traceable in the run log instead of silently vanishing.
    """

    source_url: str
    funder: str
    title: str
    text: str                       # stripped page text, never sent to a model whole
    tier: int
    programs_hint: list[Program] = field(default_factory=list)
    http_status: int | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parse_notes: list[str] = field(default_factory=list)


@dataclass
class Opportunity:
    """The record Mauri reads. Field set is §6 verbatim."""

    # identity
    id: str
    title: str
    funder: str

    # the numbers that decide everything
    award_min: int | None
    award_max: int | None
    deadline: date | None
    estimated_effort_hours: int | None   # vs the 10-hour cap

    # matching
    program_match: list[Program]
    score: int                   # 0-100
    score_rationale: str         # one sentence, human-readable

    # trust — non-negotiable
    source_url: str              # REQUIRED. no URL, no record.
    verified: bool               # did we read the funder's own page?
    needs_human_check: bool      # ambiguous deadline/amount → flag, don't guess
    fetched_at: datetime

    def __post_init__(self) -> None:
        if not self.source_url or not self.source_url.startswith(("http://", "https://")):
            raise ValueError(
                f"Opportunity {self.title!r} has no usable source_url. "
                "CLAUDE.md §6: no URL, no record."
            )
        # A missing amount or deadline is always a human-check, no exceptions.
        if self.award_max is None or self.deadline is None:
            self.needs_human_check = True

    @property
    def section(self) -> Section:
        return Section.SCORED if self.award_max is not None else Section.AMOUNT_NOT_STATED

    @property
    def days_until_deadline(self) -> int | None:
        if self.deadline is None:
            return None
        return (self.deadline - date.today()).days

    def to_dict(self) -> dict:
        """Plain dict. Sinks decide presentation; this is just transport."""
        return {
            "id": self.id,
            "title": self.title,
            "funder": self.funder,
            "award_min": self.award_min,
            "award_max": self.award_max,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "estimated_effort_hours": self.estimated_effort_hours,
            "program_match": [p.value for p in self.program_match],
            "score": self.score,
            "score_rationale": self.score_rationale,
            "source_url": self.source_url,
            "verified": self.verified,
            "needs_human_check": self.needs_human_check,
            "fetched_at": self.fetched_at.isoformat(),
            "section": self.section.value,
        }


class StopReason(str, Enum):
    """Every run ends on exactly one of these, and the Runs tab shows which (§8)."""

    TARGET_MET = "target_met"
    BUDGET = "budget"
    SOURCES_EXHAUSTED = "sources_exhausted"
    DISABLED = "disabled"          # ENABLED=FALSE, exited at step 0
    ERROR = "error"


@dataclass
class RunLog:
    """One row of the Runs tab, and the unit of evidence for 'experiments run'."""

    started_at: datetime
    finished_at: datetime | None = None
    sources_attempted: int = 0
    sources_ok: int = 0
    sources_failed: int = 0
    candidates_parsed: int = 0
    rejected_by_filter: dict[str, int] = field(default_factory=dict)
    opportunities_scored: int = 0
    opportunities_not_stated: int = 0
    usd_spent: float = 0.0
    stop_reason: StopReason | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "sources_attempted": self.sources_attempted,
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "candidates_parsed": self.candidates_parsed,
            "rejected_by_filter": dict(self.rejected_by_filter),
            "opportunities_scored": self.opportunities_scored,
            "opportunities_not_stated": self.opportunities_not_stated,
            "usd_spent": round(self.usd_spent, 4),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "notes": list(self.notes),
        }
