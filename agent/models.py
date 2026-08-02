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


class SourceKind(str, Enum):
    """Where a record came from — a hand-picked funder page, or an indexed database.

    Worth carrying on the record rather than inferring later, because the two have
    different trust profiles. A funder page is one organization Mauri already knows,
    read directly. A database row is a complete public list nobody curated, so it is
    broader but arrives with no relationship attached.
    """

    FUNDER_PAGE = "funder_page"          # a source in sources.py we chose by hand
    INDEXED_DATABASE = "indexed_database"  # CA Grants Portal / Grants.gov (apis.py)

    @property
    def label(self) -> str:
        """§9: no technical vocabulary on anything Mauri reads."""
        return {
            SourceKind.FUNDER_PAGE: "Funder's own page",
            SourceKind.INDEXED_DATABASE: "Public grants database",
        }[self]


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

    # provenance — defaulted so existing construction sites stay valid
    source_kind: SourceKind = SourceKind.FUNDER_PAGE

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
            "source_kind": self.source_kind.value,
            "source_kind_label": self.source_kind.label,
        }


class StopReason(str, Enum):
    """Every run ends on exactly one of these, and the Runs tab shows which (§8)."""

    TARGET_MET = "target_met"
    BUDGET = "budget"
    SOURCES_EXHAUSTED = "sources_exhausted"
    DISABLED = "disabled"          # ENABLED=FALSE, exited at step 0
    ERROR = "error"
    PARTIAL = "partial"            # something broke mid-run; we wrote what we had


class SourceStatus(str, Enum):
    """Per-source outcome. One broken source must never look like a quiet week.

    The distinction that matters to Mauri is UNREACHABLE vs NO_RESULTS. Both produce
    zero rows, but one means "go look yourself" and the other means "nothing new".
    Collapsing them into a short list with no explanation is the failure mode this
    enum exists to prevent.
    """

    OK = "ok"                      # reached it, and something came through
    NO_RESULTS = "no_results"      # reached it, nothing survived the filters
    UNREACHABLE = "unreachable"    # fetch failed — down, moved, or blocking us
    UNPARSEABLE = "unparseable"    # fetched, but the page broke the parser
    NOT_CHECKED = "not_checked"    # no confirmed URL on file (sources.py)


@dataclass
class SourceHealth:
    """What happened at one source this run. Rendered above the list Mauri reads."""

    name: str
    funder: str
    status: SourceStatus
    detail: str = ""
    candidates: int = 0            # survivors of the free filters from this source

    @property
    def degraded(self) -> bool:
        """Something broke *this week* — as opposed to this source simply having
        nothing on offer, or never having had an address to check.

        NOT_CHECKED is deliberately excluded. Two warm funds have no public grants
        page on file and may never get one, so counting them as a weekly failure
        makes the alert fire every single week — which is the same as no alert.
        """
        return self.status in (SourceStatus.UNREACHABLE, SourceStatus.UNPARSEABLE)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "funder": self.funder,
            "status": self.status.value,
            "detail": self.detail,
            "candidates": self.candidates,
        }


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
    source_health: list[SourceHealth] = field(default_factory=list)

    def record(self, health: SourceHealth) -> None:
        """Log one source's outcome and keep the aggregate counters in step."""
        self.source_health.append(health)
        if health.status is SourceStatus.UNREACHABLE:
            self.sources_failed += 1
        elif health.status is not SourceStatus.NOT_CHECKED:
            self.sources_ok += 1

    def credit(self, funder: str, n: int = 1) -> None:
        """Attribute surviving candidates back to the source that produced them."""
        for h in self.source_health:
            if h.funder == funder:
                h.candidates += n
                if h.status is SourceStatus.NO_RESULTS:
                    h.status = SourceStatus.OK
                return

    def finalize_health(self) -> None:
        """A source that answered but yielded nothing is NO_RESULTS, not OK.

        Called once after the crawl, when candidate counts are final.
        """
        for h in self.source_health:
            if h.status is SourceStatus.OK and h.candidates == 0:
                h.status = SourceStatus.NO_RESULTS

    @property
    def degraded_sources(self) -> list[SourceHealth]:
        """Sources that broke this week."""
        return [h for h in self.source_health if h.degraded]

    @property
    def unchecked_sources(self) -> list[SourceHealth]:
        """Standing gaps in the registry — no address on file, so never checked."""
        return [h for h in self.source_health
                if h.status is SourceStatus.NOT_CHECKED]

    @property
    def checked_sources(self) -> list[SourceHealth]:
        """Sources that answered, whether or not they had anything for us."""
        return [h for h in self.source_health
                if h.status in (SourceStatus.OK, SourceStatus.NO_RESULTS)]

    @property
    def coverage_complete(self) -> bool:
        return not self.degraded_sources

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
            "source_health": [h.to_dict() for h in self.source_health],
            "coverage_complete": self.coverage_complete,
        }
