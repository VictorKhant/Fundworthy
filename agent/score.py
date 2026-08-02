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
from .models import (DeadlineType, FunderType, Opportunity, RawCandidate,
                     SourceKind, stable_id)
from .sources import Source
from .verify import quote_on_page, year_in_quote

log = logging.getLogger(__name__)

TRIAGE_MODEL = "claude-haiku-4-5"    # §5: Haiku for triage
SCORING_MODEL = "claude-sonnet-4-6"  # §5: Sonnet for final scoring

# USD per million tokens, standard published rates (Haiku 4.5 $1/$5, Sonnet 4.6
# $3/$15). We budget at the standard rate: over-estimating spend makes the ceiling
# stop us early, which is the safe direction to be wrong in.
PRICING = {
    TRIAGE_MODEL: {"input": 1.00, "output": 5.00},
    SCORING_MODEL: {"input": 3.00, "output": 15.00},
}

TRIAGE_TEXT_CAP = 8_000     # chars ≈ 2k tokens (§8: "cap at ~2k tokens per candidate")
SCORING_TEXT_CAP = 12_000
TRIAGE_MAX_TOKENS = 512
SCORING_MAX_TOKENS = 8_000  # headroom: max_tokens caps thinking + response on Sonnet 4.6

# Sonnet 4.6 will not cache a prefix shorter than 2048 tokens — a cache_control marker
# on a shorter prompt is silently ignored, no error and no saving. Today SCORING_SYSTEM
# is ~554 tokens, so caching is genuinely off; it turns on by itself once the Org Profile
# boilerplate (§4) lands in the prompt. Asserting the threshold rather than pasting a
# marker that does nothing keeps the code honest about which it is.
SONNET_CACHE_MIN_TOKENS = 2048


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

_ORG_PREAMBLE = """\
You are screening funding opportunities for RISE San Diego, a nonprofit working \
across San Diego County and Imperial County (the Far South / Border North region \
spans both).

The person reading your output is RISE's COO. She has one hour on Thursday morning
and a hard cap of 10 collective team-hours per application. Her stated problem is
NOT that she cannot find grants — she can already find plenty. It is that what she
finds is too small to justify a 10-hour application.

So: surfacing a marginal opportunity costs her more than missing one. Be strict.

This week she is looking for funding for these programs, and they live in different
funder universes:
"""


def org_context(cfg: Config) -> str:
    """The shared prompt prefix, built from the program cards Mauri ticked.

    This used to be a hardcoded description of three programs. It is now generated
    from the cards, which is the entire point of making them editable: when she adds
    RISE Now or rewrites what RISE Arts is looking for, the model's instructions change
    with it and nobody edits Python.

    Still byte-stable *within* a run — every candidate in a run sees the same prefix —
    so prompt caching behaves exactly as before.
    """
    lines = [_ORG_PREAMBLE]
    for card in cfg.programs:
        lines.append(f"\n- {card.slug} — {card.name}.")
        if card.summary:
            lines.append(f"  {card.summary}")
        if card.what_it_funds:
            lines.append(f"  Funds: {card.what_it_funds}")
        if card.keywords:
            lines.append(f"  Funder-facing language: {', '.join(card.keywords)}.")
        if card.funder_types:
            lines.append(f"  Typical funders: {', '.join(card.funder_types)}.")
        floor = card.floor(cfg.min_award)
        if floor != cfg.min_award:
            lines.append(f"  Award floor for this program: ${floor:,}.")
        if not (card.summary or card.keywords):
            # An un-filled card is a real state — she added the program but has not
            # described it yet. Say so rather than letting the model invent a remit.
            lines.append("  (No description recorded yet. Judge fit conservatively and "
                         "say in the rationale that this program's card is empty.)")
    return "\n".join(lines) + "\n"

_TRIAGE_RULES = """
Your job is one binary decision: is this page an open funding opportunity that RISE
could actually apply for?

Answer false for: past grantee lists, panelist calls, annual reports, staff pages,
programs for individual artists only, programs restricted to organizations RISE is
not, and anything already closed.
"""

_SCORING_RULES = """
Score this opportunity 0-100 for RISE, write one sentence explaining the score in
language the COO can act on, and fill in the funder profile she asked for.

Weights — these are the COO's own, given directly (CLAUDE.md §11 Q5, answered):
  40  program fit
  35  award size relative to the floor
  25  can this application realistically be finished before the deadline

Nothing else moves the score. In particular:

- Funder warmth is gone. RISE already receives money from the funders it has
  relationships with and does not want to reapply, so a relationship is a reason to
  leave a funder out of the search entirely — never a reason to rank it higher. You are
  not told whether RISE knows a funder, because it must not change the score.
- The funder's 990 filing history is shown to the COO as data next to the result. It is
  not a scoring criterion. Where 990 context is given to you below, use it to judge
  PROGRAM FIT better — a funder whose past grants look nothing like RISE's work is a
  weak fit however well the page reads — not as a score of its own.

On the 25 points for finishing in time: judge the application against the deadline, not
in the abstract. A grant closing in three weeks that needs an audited financial
statement, three letters of support and a board resolution is not a 25; a two-page
letter of interest due in two months is. Say so in the rationale when the calendar is
the problem.

There are two kinds of field below and they are held to different standards.

SOURCED fields — award_min_stated, award_max_stated, award_typical_stated,
deadline_stated, deadline_type, geography_stated, contact_note — may ONLY be filled
from the page text in front of you. For each one you fill, copy the exact sentence you
read it from into its *_quote field, verbatim and character-for-character. A quote that
is not a literal substring of the page is rejected and the value thrown away, so never
paraphrase, reconstruct, tidy up, or stitch together a quote. If the page does not say
it, set BOTH the value and its quote to null. Never infer, estimate, or recall a number
from anywhere but this page. The deadline quote MUST contain the full date including
the year.

INFERRED fields — funder_type, service_areas, confidence_pct — are your judgement and
are shown to the COO labelled as such. Use everything on the page. Do not force them:
"unknown" and an empty list are real answers.

Also:
- deadline_type is "fixed" when the page names one date, "rolling" when it says
  applications are accepted on an ongoing basis or in multiple cycles, and "unknown"
  otherwise. "rolling" needs a quote saying so, same as any sourced field.
- award_typical_stated is what the funder says they TYPICALLY or on AVERAGE award —
  not the maximum, and never a total program budget or a since-inception figure.
- contact_note: only a name, email, or phone number that literally appears on the page.
- confidence_pct is how confident you are that this funder would fund one of the RISE
  programs listed above. Be honest and use the low end when the fit is thin.
- estimated_effort_hours is your read of what a competitive application costs this
  team in WORKING HOURS. Above 10 is a real signal, not a rounding error — say so.
- application_lead_time_days is different and is about the CALENDAR: how many days
  from starting to being able to submit, given what the application requires. Audited
  financials, board resolutions, letters of support and reference forms all depend on
  other people and add weeks that have nothing to do with hours of work. If this
  exceeds the days left before the deadline, the opportunity is not feasible — score
  the "finish in time" component at or near zero and say so plainly in the rationale.
- time_to_funds_days is your estimate of how long AFTER submitting before the money
  would actually reach RISE's bank account — decision timeline plus disbursement. A
  nonprofit's cash flow depends on this and funders rarely state it, so estimate from
  what the page says about review cycles and award dates. This is a judgement, and it
  is labelled as one; null if you have nothing to go on.
- score_rationale is one sentence, no preamble, no hedging, written for someone
  deciding whether to spend ten hours.
- needs_human_check is NOT "some information was missing". Missing information is the
  normal case — most funders publish neither an amount nor a deadline — and it is
  already reflected in the score. Set it true only when YOU reported something you
  could not fully confirm from the page. Most results should be false.
- If the text you are given is not readable prose — binary, a PDF stream, markup
  fragments — do not score it. Return score 0, say so in the rationale, and set
  needs_human_check true.
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

# Sourced field -> the quote field that has to back it. Driving both the schema and the
# verification loop off one table means a new column cannot be added to the prompt
# without also being gated — the failure mode would be a field that looks verified and
# is not.
QUOTE_BACKED: dict[str, str] = {
    "award_min_stated": "award_quote",
    "award_max_stated": "award_quote",
    "award_typical_stated": "award_typical_quote",
    "deadline_stated": "deadline_quote",
    "geography_stated": "geography_quote",
    "contact_note": "contact_quote",
}


def scoring_schema(program_slugs: list[str]) -> dict:
    """The response schema, with program_match restricted to the ticked programs.

    Built per run rather than hardcoded, because the programs are now editable cards.
    A program Mauri adds on Sunday has to be selectable by the model on Wednesday
    without anyone editing this file.
    """
    return {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "description": "0-100."},
            "score_rationale": {"type": "string", "description": "Exactly one sentence."},
            "program_match": {
                "type": "array",
                "items": {"type": "string",
                          "enum": program_slugs or ["NONE"]},
            },
            "estimated_effort_hours": {
                "type": ["integer", "null"],
                "description": "WORKING HOURS for a competitive application, or null.",
            },
            "application_lead_time_days": {
                "type": ["integer", "null"],
                "description": (
                    "CALENDAR days from starting to being able to submit, given what "
                    "the application requires from other people (audited financials, "
                    "board resolutions, letters of support). Null if unknowable."
                ),
            },
            "time_to_funds_days": {
                "type": ["integer", "null"],
                "description": (
                    "Your estimate of days from SUBMITTING to the money reaching the "
                    "bank — review cycle plus disbursement. A judgement, not a quote. "
                    "Null if the page gives nothing to go on."
                ),
            },

            # --- sourced: each needs its verbatim quote or it is discarded ---
            "award_min_stated": {
                "type": ["integer", "null"],
                "description": "Only if a per-award minimum appears in the text. Else null.",
            },
            "award_max_stated": {
                "type": ["integer", "null"],
                "description": "Only if a per-award maximum appears in the text. Else null.",
            },
            "award_quote": {
                "type": ["string", "null"],
                "description": (
                    "The exact sentence, copied verbatim from the page text, that states "
                    "the award minimum/maximum above — character-for-character, no "
                    "paraphrasing. null if no award amount appears in the text."
                ),
            },
            "award_typical_stated": {
                "type": ["integer", "null"],
                "description": (
                    "The award the funder says it TYPICALLY or on average makes. Not the "
                    "maximum. Never a total program budget or a since-inception total. "
                    "null unless the page states it."
                ),
            },
            "award_typical_quote": {
                "type": ["string", "null"],
                "description": "The exact sentence stating the typical award. Verbatim.",
            },
            "deadline_stated": {
                "type": ["string", "null"],
                "description": "YYYY-MM-DD, only if a deadline appears in the text. Else null.",
            },
            "deadline_quote": {
                "type": ["string", "null"],
                "description": (
                    "The exact sentence, copied verbatim, that states the deadline above. "
                    "It MUST contain the full date including the year. null otherwise."
                ),
            },
            "deadline_type": {
                "type": "string",
                "enum": ["fixed", "rolling", "unknown"],
                "description": (
                    "'rolling' only if the page says applications are accepted on an "
                    "ongoing basis or in multiple cycles, and only with a quote."
                ),
            },
            "deadline_type_quote": {
                "type": ["string", "null"],
                "description": "Verbatim sentence supporting 'rolling'. null otherwise.",
            },
            "geography_stated": {
                "type": ["string", "null"],
                "description": "The geography the funder says it funds. null if unstated.",
            },
            "geography_quote": {
                "type": ["string", "null"],
                "description": "The exact sentence stating that geography. Verbatim.",
            },
            "contact_note": {
                "type": ["string", "null"],
                "description": (
                    "A contact name, email, or phone number that literally appears on the "
                    "page. null otherwise — never construct one from a domain name."
                ),
            },
            "contact_quote": {
                "type": ["string", "null"],
                "description": "The exact sentence containing that contact. Verbatim.",
            },

            # --- inferred: the model's judgement, labelled as such in the UI ---
            "funder_type": {
                "type": "string",
                "enum": ["private_foundation", "corporate", "community", "government",
                         "public_agency", "other", "unknown"],
            },
            "service_areas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What this funder funds, e.g. STEM, Arts, Youth, Equity.",
            },
            "confidence_pct": {
                "type": ["integer", "null"],
                "description": "0-100: how confident you are this funder would fund a "
                               "RISE program listed above.",
            },

            "needs_human_check": {
                "type": "boolean",
                "description": (
                    "TRUE ONLY IF you reported a value above that you could not fully "
                    "confirm from the page text — an amount, deadline, geography or "
                    "contact you are unsure of. "
                    "FALSE when information is simply ABSENT: a funder that never "
                    "states an award amount or a deadline is normal and is not a "
                    "problem to flag. Most results should be FALSE. This field moves "
                    "the result into a separate 'needs your eyes' block, so flagging "
                    "everything makes the block meaningless and buries good results."
                ),
            },
        },
        "required": [
            "score", "score_rationale", "program_match", "estimated_effort_hours",
            "application_lead_time_days", "time_to_funds_days",
            "award_min_stated", "award_max_stated", "award_quote",
            "award_typical_stated", "award_typical_quote",
            "deadline_stated", "deadline_quote", "deadline_type", "deadline_type_quote",
            "geography_stated", "geography_quote", "contact_note", "contact_quote",
            "funder_type", "service_areas", "confidence_pct", "needs_human_check",
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

def triage(candidate: RawCandidate, budget: Budget,
           cfg: Config | None = None) -> tuple[bool, str]:
    """Binary relevant/not. Cheap model, capped text, no thinking."""
    system = (org_context(cfg) if cfg else _ORG_PREAMBLE) + _TRIAGE_RULES
    body = _text_block(
        f"Funder: {candidate.funder}\n"
        f"Page title: {candidate.title}\n"
        f"URL: {candidate.source_url}\n\n"
        f"{candidate.text[:TRIAGE_TEXT_CAP]}"
    )
    budget.check(TRIAGE_MODEL, _estimate_tokens(system + body), TRIAGE_MAX_TOKENS)

    resp = _client().messages.create(
        model=TRIAGE_MODEL,
        max_tokens=TRIAGE_MAX_TOKENS,
        system=system,
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
              budget: Budget, facts_990: dict | None = None) -> Opportunity:
    """Full score + rationale. The system prompt is cached across candidates."""
    system = org_context(cfg) + _SCORING_RULES
    body = _text_block(
        f"Award floor for this run: ${cfg.min_award:,}\n"
        f"Today: {date.today().isoformat()}\n"
        # The "[WARM — RISE has an existing relationship]" hint used to be appended
        # here. Removed with the warmth weight: telling the model about a relationship
        # it must not score on is just an invitation to score on it anyway.
        f"Funder: {candidate.funder}"
        # 990 context, when we have it. Given so the model can judge PROGRAM FIT
        # against what this funder actually is — a $500M national foundation and a
        # $350k county fund read the same on a web page — not as a criterion of its own.
        + (f"\nFunder's IRS filing: {_990_line(facts_990)}" if _990_line(facts_990) else "")
        + f"\nPage title: {candidate.title}\nURL: {candidate.source_url}\n\n"
        f"{candidate.text[:SCORING_TEXT_CAP]}"
    )
    budget.check(SCORING_MODEL, _estimate_tokens(system + body), SCORING_MAX_TOKENS)

    system_block: dict = {"type": "text", "text": system}
    if _estimate_tokens(system) >= SONNET_CACHE_MIN_TOKENS:
        # Worth caching: the same prompt is reused across every candidate this run.
        system_block["cache_control"] = {"type": "ephemeral"}

    resp = _client().messages.create(
        model=SCORING_MODEL,
        max_tokens=SCORING_MAX_TOKENS,
        system=[system_block],
        messages=[{"role": "user", "content": body}],
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema",
                       "schema": scoring_schema(cfg.programs_active)},
            "effort": "medium",
        },
    )
    cost = budget.record(SCORING_MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    data = _first_json(resp)

    page_text = candidate.text
    needs_check = bool(data.get("needs_human_check"))

    # --- Accuracy gate (§6). A stated award/deadline is trusted only if the model
    # returned the verbatim sentence it read it from AND that sentence is literally on
    # the page. Anything unverifiable is nulled and flagged — never shown as a number.
    award_min = data.get("award_min_stated")
    award_max = data.get("award_max_stated")
    if (award_min is not None or award_max is not None) and not quote_on_page(
        data.get("award_quote"), page_text
    ):
        log.warning("  ⚠ award unverified (quote not on page) — nulling %s/%s",
                    award_min, award_max)
        award_min = award_max = None
        needs_check = True

    deadline = None
    deadline_iso = data.get("deadline_stated")
    if deadline_iso:
        dquote = data.get("deadline_quote")
        if quote_on_page(dquote, page_text) and year_in_quote(deadline_iso, dquote):
            try:
                deadline = date.fromisoformat(deadline_iso)
            except ValueError:
                log.warning("unparseable deadline %r — dropping", deadline_iso)
                needs_check = True
        else:
            log.warning("  ⚠ deadline unverified (quote/year not on page) — dropping %r",
                        deadline_iso)
            needs_check = True

    # The same gate, applied to the columns Mauri added. Each is only kept if its own
    # verbatim quote is literally on the page; otherwise it is dropped and flagged. The
    # point of routing these through one helper is that a new sourced column cannot be
    # added to the schema and quietly skip verification.
    award_typical, ok = _gated(data, "award_typical_stated", "award_typical_quote",
                               page_text)
    needs_check = needs_check or not ok

    geography, ok = _gated(data, "geography_stated", "geography_quote", page_text)
    needs_check = needs_check or not ok

    contact_note, ok = _gated(data, "contact_note", "contact_quote", page_text)
    needs_check = needs_check or not ok

    # "Rolling" is a claim about the funder's process, so it needs a quote like any
    # other sourced value. "fixed" is already backed by the verified deadline above.
    deadline_type = DeadlineType.UNKNOWN
    raw_type = str(data.get("deadline_type") or "unknown")
    if raw_type == "rolling" and quote_on_page(data.get("deadline_type_quote"), page_text):
        deadline_type = DeadlineType.ROLLING
    elif deadline is not None:
        deadline_type = DeadlineType.FIXED
    elif raw_type == "rolling":
        log.warning("  ⚠ 'rolling' unverified (quote not on page) — leaving unknown")
        needs_check = True

    # Inferred fields. No quote gate — they are judgement, and the UI says so.
    funder_type = _as_enum(FunderType, data.get("funder_type"), FunderType.UNKNOWN)
    service_areas = [str(s)[:60] for s in (data.get("service_areas") or [])][:8]
    confidence_pct = data.get("confidence_pct")
    if confidence_pct is not None:
        confidence_pct = max(0, min(100, int(confidence_pct)))

    active = cfg.programs_active
    programs = [p for p in (data.get("program_match") or []) if p in active]

    opp = Opportunity(
        id=stable_id(candidate.source_url, candidate.title),
        title=candidate.title[:300],
        funder=candidate.funder,
        award_min=award_min,
        award_max=award_max,
        deadline=deadline,
        estimated_effort_hours=data.get("estimated_effort_hours"),
        program_match=programs or list(active),
        score=max(0, min(100, int(data["score"]))),
        score_rationale=str(data["score_rationale"]).strip(),
        source_url=candidate.source_url,
        verified=True,
        needs_human_check=needs_check,
        fetched_at=datetime.now(timezone.utc),
        award_typical=award_typical,
        deadline_type=deadline_type,
        funder_type=funder_type,
        service_areas=service_areas,
        geography=geography,
        confidence_pct=confidence_pct,
        contact_note=contact_note,
        found_on=date.today(),
        source_kind=(SourceKind.INDEXED_DATABASE if source.is_api
                     else SourceKind.FUNDER_PAGE),
        # The COO's two time criteria. Both are judgement — funders almost never state
        # either — and both are rendered with an AI marker.
        application_lead_time_days=_bounded(data.get("application_lead_time_days"), 400),
        time_to_funds_days=_bounded(data.get("time_to_funds_days"), 800),
        # 990 facts come from the funder lookup, not from this page, so they bypass the
        # quote gate — nothing here is being claimed about the opportunity itself.
        ein=(facts_990 or {}).get("ein"),
        form_990_url=(facts_990 or {}).get("form_990_url"),
        form_990_year=(facts_990 or {}).get("form_990_year"),
        form_990_total_revenue=(facts_990 or {}).get("form_990_total_revenue"),
        form_990_total_expenses=(facts_990 or {}).get("form_990_total_expenses"),
        form_990_available=bool((facts_990 or {}).get("form_990_year")) or None,
    )
    log.info("  scored %3d  %-30s  %s  ($%.5f)",
             opp.score, opp.funder[:30], opp.title[:40], cost)
    return opp


def _gated(data: dict, value_key: str, quote_key: str, page_text: str):
    """Return (value, verified). A value whose quote is not literally on the page is
    thrown away — §6 does not distinguish between a confabulated award amount and a
    confabulated contact email."""
    value = data.get(value_key)
    if value in (None, "", []):
        return None, True
    if quote_on_page(data.get(quote_key), page_text):
        return value, True
    log.warning("  ⚠ %s unverified (quote not on page) — dropping %r", value_key, value)
    return None, False


def _bounded(value, ceiling: int) -> int | None:
    """A day count that survives being wrong. A model that answers 99999 should give us
    nothing rather than a number the UI renders as fact."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= ceiling else None


def _990_line(facts: dict | None) -> str:
    from .irs990 import summary_line

    return summary_line(facts)


def _as_enum(enum_cls, raw, default):
    try:
        return enum_cls(str(raw))
    except (ValueError, TypeError):
        return default
