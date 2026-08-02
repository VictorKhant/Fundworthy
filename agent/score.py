"""Tiered LLM scoring. (CLAUDE.md §7, §8)

Three tiers, cheapest first:

  1. free      deterministic filters (filters.py) — already run before we get here
  2. cheap     Haiku triage on survivors, binary relevant/not, text capped
  3. expensive Sonnet scoring + rationale on the top N only

Every call goes through `Budget`, which refuses to spend past the $1.00 weekly
ceiling (§8). The ceiling is checked *before* each request using a token estimate,
not after, so the run can never discover it has overspent.

Model choice follows §5 exactly — Haiku for triage, Sonnet for final scoring. That
is a deliberate cost-tiering decision by the spec, not a default.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .config import Config
from .models import Opportunity, Program, RawCandidate, stable_id
from .sources import Source

log = logging.getLogger(__name__)

TRIAGE_MODEL = "claude-haiku-4-5"   # §5: Haiku for triage
SCORING_MODEL = "claude-sonnet-5"   # §5: Sonnet for final scoring

# USD per million tokens. Sonnet 5 has introductory pricing ($2/$10) through
# 2026-08-31, but we budget at the standard rate: over-estimating spend makes the
# ceiling stop us early, which is the safe direction to be wrong in.
PRICING = {
    TRIAGE_MODEL: {"input": 1.00, "output": 5.00},
    SCORING_MODEL: {"input": 3.00, "output": 15.00},
}

TRIAGE_TEXT_CAP = 8_000     # chars ≈ 2k tokens (§8: "cap at ~2k tokens per candidate")
SCORING_TEXT_CAP = 12_000
TRIAGE_MAX_TOKENS = 512
SCORING_MAX_TOKENS = 8_000  # headroom: max_tokens caps thinking + response on Sonnet 5

# Sonnet 5 will not cache a prefix shorter than this — a cache_control marker on a
# shorter prompt is silently ignored, no error and no saving. Today SCORING_SYSTEM is
# ~554 tokens, so caching is genuinely off; it turns on by itself once the Org Profile
# boilerplate (§4) lands in the prompt. Asserting the threshold rather than pasting a
# marker that does nothing keeps the code honest about which it is.
SONNET_CACHE_MIN_TOKENS = 1024


class BudgetExceeded(RuntimeError):
    """Raised instead of making a call that would breach the ceiling."""


@dataclass
class Budget:
    """Hard spend ceiling. No exceptions, no retries past it (§8)."""

    ceiling_usd: float = 1.00
    spent_usd: float = 0.0
    calls: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def _cost(self, model: str, in_tok: int, out_tok: int) -> float:
        p = PRICING[model]
        return (in_tok * p["input"] + out_tok * p["output"]) / 1_000_000

    def check(self, model: str, est_in: int, est_out: int) -> None:
        """Refuse a call whose worst case would breach the ceiling."""
        projected = self.spent_usd + self._cost(model, est_in, est_out)
        if projected > self.ceiling_usd:
            raise BudgetExceeded(
                f"${projected:.4f} would exceed the ${self.ceiling_usd:.2f} ceiling "
                f"(spent ${self.spent_usd:.4f} over {self.calls} calls)"
            )

    def record(self, model: str, in_tok: int, out_tok: int) -> float:
        cost = self._cost(model, in_tok, out_tok)
        self.spent_usd += cost
        self.calls += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + cost
        return cost


# --- prompts ------------------------------------------------------------------

# Kept byte-stable so it caches across the N scoring calls in a run (min cacheable
# prefix on Sonnet 5 is 1024 tokens). Nothing per-candidate goes in here.
ORG_CONTEXT = """\
You are screening funding opportunities for RISE San Diego, a nonprofit working \
across San Diego County and Imperial County (the Far South / Border North region \
spans both). RISE runs three programs, and they live in different funder universes:

- RULFP — RISE Urban Leadership Fellows. Leadership pipeline, adaptive leadership,
  resident-led civic engagement, BIPOC leadership development, cohort fellowship,
  DEIA capacity building. Funders: leadership, equity, community foundations.
- RESILIENCE — RISE Resilience & Renewal. Nonprofit leader burnout, whole-body
  leadership, somatic practice, polyvagal theory, wellness, workforce retention,
  health tech. Funders: health and behavioral health. This program was born out of
  Alliance Healthcare Foundation's i2 Challenge.
- ARTS — RISE Arts. Arts and social justice, artists from historically marginalized
  communities, creative placemaking, cultural equity, arts capacity building.
  Funders: public arts agencies, arts foundations.

The person reading your output is RISE's COO. She has one hour on Thursday morning
and a hard cap of 10 collective team-hours per application. Her stated problem is
NOT that she cannot find grants — she already spends 16 hours a week finding them.
It is that what she finds is too small to justify a 10-hour application.

So: surfacing a marginal opportunity costs her more than missing one. Be strict.
"""

TRIAGE_SYSTEM = ORG_CONTEXT + """
Your job is one binary decision: is this page an open funding opportunity that RISE
could actually apply for?

Answer false for: past grantee lists, panelist calls, annual reports, staff pages,
programs for individual artists only, programs restricted to organizations RISE is
not, and anything already closed.
"""

SCORING_SYSTEM = ORG_CONTEXT + """
Score this opportunity 0-100 for RISE, and write one sentence explaining the score
in language the COO can act on.

Weights (CLAUDE.md §7 — PROVISIONAL, pending Mauri's forced-rank in §11 Q5):
  35  award size relative to the floor
  25  program fit, weighted toward her three priorities
  20  funder warmth
  15  effort vs the 10-hour cap
   5  deadline runway

Rules you must not break:
- Judge only what is in the page text given to you. If the amount or deadline is not
  there, say so — never infer, estimate, or recall a number from elsewhere.
- estimated_effort_hours is your read of what a competitive application costs this
  team. Above 10 is a real signal, not a rounding error — say so.
- score_rationale is one sentence, no preamble, no hedging, written for someone
  deciding whether to spend ten hours.
"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_opportunity": {
            "type": "boolean",
            "description": "True only if RISE could submit an application to this.",
        },
        "reason": {"type": "string", "description": "At most 15 words."},
    },
    "required": ["is_opportunity", "reason"],
    "additionalProperties": False,
}

SCORING_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "0-100."},
        "score_rationale": {"type": "string", "description": "Exactly one sentence."},
        "program_match": {
            "type": "array",
            "items": {"type": "string", "enum": ["RULFP", "RESILIENCE", "ARTS"]},
        },
        "estimated_effort_hours": {
            "type": ["integer", "null"],
            "description": "Hours for a competitive application, or null if unknowable.",
        },
        "award_min_stated": {
            "type": ["integer", "null"],
            "description": "Only if a per-award minimum appears in the text. Else null.",
        },
        "award_max_stated": {
            "type": ["integer", "null"],
            "description": "Only if a per-award maximum appears in the text. Else null.",
        },
        "deadline_stated": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD, only if a deadline appears in the text. Else null.",
        },
        "needs_human_check": {"type": "boolean"},
    },
    "required": [
        "score", "score_rationale", "program_match", "estimated_effort_hours",
        "award_min_stated", "award_max_stated", "deadline_stated", "needs_human_check",
    ],
    "additionalProperties": False,
}


def _client():
    import anthropic

    return anthropic.Anthropic()


def _estimate_tokens(text: str) -> int:
    """~4 chars per token. Only used for the pre-call budget check, where being
    roughly right early beats being exactly right too late."""
    return len(text) // 4 + 200


def _text_block(payload: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", payload).strip()


def _first_json(response) -> dict:
    """output_config.format guarantees the first text block is valid JSON."""
    for block in response.content:
        if block.type == "text":
            return json.loads(block.text)
    raise ValueError("no text block in response")


# --- tier 2: Haiku triage -----------------------------------------------------

def triage(candidate: RawCandidate, budget: Budget) -> tuple[bool, str]:
    """Binary relevant/not. Cheap model, capped text, no thinking."""
    body = _text_block(
        f"Funder: {candidate.funder}\n"
        f"Page title: {candidate.title}\n"
        f"URL: {candidate.source_url}\n\n"
        f"{candidate.text[:TRIAGE_TEXT_CAP]}"
    )
    budget.check(TRIAGE_MODEL, _estimate_tokens(TRIAGE_SYSTEM + body), TRIAGE_MAX_TOKENS)

    resp = _client().messages.create(
        model=TRIAGE_MODEL,
        max_tokens=TRIAGE_MAX_TOKENS,
        system=TRIAGE_SYSTEM,
        messages=[{"role": "user", "content": body}],
        output_config={"format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
    )
    cost = budget.record(TRIAGE_MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    data = _first_json(resp)
    log.debug("  triage %-40s -> %s (%s) $%.5f",
              candidate.title[:40], data["is_opportunity"], data["reason"], cost)
    return bool(data["is_opportunity"]), str(data["reason"])


# --- tier 3: Sonnet scoring ---------------------------------------------------

def score_one(candidate: RawCandidate, source: Source, cfg: Config,
              budget: Budget) -> Opportunity:
    """Full score + rationale. The system prompt is cached across candidates."""
    floor = (f"${cfg.min_award:,}"
             + (" (PLACEHOLDER — not yet set by the stakeholder)"
                if cfg.min_award_is_placeholder else ""))
    body = _text_block(
        f"Award floor for this run: {floor}\n"
        f"Today: {date.today().isoformat()}\n"
        f"Funder: {candidate.funder}"
        + ("  [WARM — RISE has an existing relationship]" if source.warm else "")
        + f"\nPage title: {candidate.title}\nURL: {candidate.source_url}\n\n"
        f"{candidate.text[:SCORING_TEXT_CAP]}"
    )
    budget.check(SCORING_MODEL, _estimate_tokens(SCORING_SYSTEM + body), SCORING_MAX_TOKENS)

    system_block: dict = {"type": "text", "text": SCORING_SYSTEM}
    if _estimate_tokens(SCORING_SYSTEM) >= SONNET_CACHE_MIN_TOKENS:
        # Worth caching: the same prompt is reused across every candidate this run.
        system_block["cache_control"] = {"type": "ephemeral"}

    resp = _client().messages.create(
        model=SCORING_MODEL,
        max_tokens=SCORING_MAX_TOKENS,
        system=[system_block],
        messages=[{"role": "user", "content": body}],
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": SCORING_SCHEMA},
            "effort": "medium",
        },
    )
    cost = budget.record(SCORING_MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    data = _first_json(resp)

    deadline = None
    if data.get("deadline_stated"):
        try:
            deadline = date.fromisoformat(data["deadline_stated"])
        except ValueError:
            log.warning("unparseable deadline %r — dropping", data["deadline_stated"])

    programs = [Program(p) for p in data.get("program_match", []) if p in Program.__members__]

    opp = Opportunity(
        id=stable_id(candidate.source_url, candidate.title),
        title=candidate.title[:300],
        funder=candidate.funder,
        award_min=data.get("award_min_stated"),
        award_max=data.get("award_max_stated"),
        deadline=deadline,
        estimated_effort_hours=data.get("estimated_effort_hours"),
        program_match=programs or list(cfg.programs_active),
        score=max(0, min(100, int(data["score"]))),
        score_rationale=str(data["score_rationale"]).strip(),
        source_url=candidate.source_url,
        verified=True,
        needs_human_check=bool(data.get("needs_human_check")),
        fetched_at=datetime.now(timezone.utc),
    )
    log.info("  scored %3d  %-30s  %s  ($%.5f)",
             opp.score, opp.funder[:30], opp.title[:40], cost)
    return opp
