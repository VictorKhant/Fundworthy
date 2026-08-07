"""Tiered LLM scoring. (CLAUDE.md)

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
from .verify import quote_on_page, unsourced_figures, year_in_quote

log = logging.getLogger(__name__)

# The defaults, and the recommendation the picker chips. §5's tiering is Haiku to
# triage and Sonnet to score; these are what you get if nobody chooses.
TRIAGE_MODEL = "anthropic:claude-haiku-4-5"
SCORING_MODEL = "anthropic:claude-sonnet-4-6"

# USD per million tokens, standard published rates. We budget at the standard rate:
# over-estimating spend makes the ceiling stop us early, which is the safe direction to
# be wrong in.
#
# **Every selectable model must have an entry.** `Budget.check` does `PRICING[model]`
# and a KeyError there aborts the run — so a model offered in the picker and missing
# here is not a mispriced run, it is no run at all. `test_score.py` asserts the two
# lists agree.
#
# Keys are `provider:model`, which is not premature: the setting is stored in that shape
# so adding a second provider later is a new entry here rather than a migration over
# everybody's saved settings. There is one provider today and the UI never shows the
# prefix.
PRICING = {
    "anthropic:claude-haiku-4-5":   {"input": 1.00, "output": 5.00},
    "anthropic:claude-sonnet-4-6":  {"input": 3.00, "output": 15.00},
    "anthropic:claude-opus-4-1":    {"input": 15.00, "output": 75.00},
}

# What the picker offers, per stage, and what each one is for in one line. Ordered
# cheapest first, which is also the order of §5's argument.
MODEL_CHOICES = {
    2: [
        {"id": "anthropic:claude-haiku-4-5", "label": "Haiku",
         "note": "Fast and very cheap. The recommended choice for a yes/no question.",
         "recommended": True},
        {"id": "anthropic:claude-sonnet-4-6", "label": "Sonnet",
         "note": "Reads more carefully, and costs roughly three times as much for a "
                 "question that is usually obvious."},
    ],
    3: [
        {"id": "anthropic:claude-haiku-4-5", "label": "Haiku",
         "note": "Cheapest, but scoring is the judgement you are actually paying for."},
        {"id": "anthropic:claude-sonnet-4-6", "label": "Sonnet",
         "note": "The recommended choice. Reads the page in full and explains its score.",
         "recommended": True},
        {"id": "anthropic:claude-opus-4-1", "label": "Opus",
         "note": "The most careful reader, and five times Sonnet's price. On a long "
                 "funder list this will hit your per-search limit before the list ends."},
    ],
}


def model_label(model_id: str) -> str:
    """"anthropic:claude-sonnet-4-6" -> "Sonnet". Falls back to the bare model name."""
    for choices in MODEL_CHOICES.values():
        for c in choices:
            if c["id"] == model_id:
                return c["label"]
    return (model_id or "").split(":")[-1]


def api_model(model_id: str) -> str:
    """Strip the provider prefix for the wire. One provider today; this is the seam."""
    return (model_id or "").split(":", 1)[-1]


def price_for(model_id: str) -> dict[str, float]:
    """The rate card for a model, accepting a bare name as well as `provider:model`.

    A KeyError here does not mis-price anything — it aborts the whole run on the first
    call. The prefix arrived with per-stage model choice, and anything still passing a
    bare `claude-sonnet-4-6` (a script, the CLI, a caller we have not thought of) would
    die rather than degrade. With one provider the mapping is unambiguous, so it is
    resolved instead.

    A genuinely unknown model still raises, and should: that is a model nobody has
    priced, and guessing a price for it would put a wrong number under a spend limit.
    """
    if model_id in PRICING:
        return PRICING[model_id]
    if ":" not in (model_id or ""):
        prefixed = f"anthropic:{model_id}"
        if prefixed in PRICING:
            return PRICING[prefixed]
    raise KeyError(
        f"{model_id!r} has no entry in PRICING, so its cost cannot be checked against "
        "the spend limit. Every selectable model needs one."
    )

TRIAGE_TEXT_CAP = 8_000     # chars ≈ 2k tokens (§8: "cap at ~2k tokens per candidate")
SCORING_TEXT_CAP = 12_000
TRIAGE_MAX_TOKENS = 512
SCORING_MAX_TOKENS = 8_000  # headroom: max_tokens caps thinking + response on Sonnet 4.6

# Sonnet 4.6 will not cache a prefix shorter than 2048 tokens — a cache_control marker
# on a shorter prompt is silently ignored, no error and no saving. `score_one` therefore
# measures the prompt and only marks it when it is worth marking.
#
# **It now clears the threshold, where it used to sit well under it.** The scoring system
# prompt is `org_context(cfg) + _SCORING_RULES`, and the three-component rubric roughly
# quintupled the second half: it measures ~2700 estimated tokens against a two-program
# org, so caching is genuinely on and every candidate after the first in a run re-reads
# that prefix at the cached rate. Triage is ~750 and stays uncached, which is why only
# `score_one` does the check.
#
# This is a saving, not a cost, but it is worth stating: `Budget` prices every call at
# the standard input rate, so a run's real spend is now *below* what the ceiling thinks.
# Over-estimating is the safe direction — the ceiling stops us early rather than late.
SONNET_CACHE_MIN_TOKENS = 2048


# The child → runner protocol. Both are recognised by `app/runner.py: _pump`, consumed,
# and kept out of the log a person reads — machine chatter in the middle of "✓ San Diego
# Foundation — 3 amounts, 1 deadline" is worse than the delay either one fixes.
#
# They live together here rather than one per module because there are two writers and
# one reader, and a marker whose prefix drifts from the parser's is a feature that
# silently stops working.
SPEND_MARKER = "::spend "
STAGE_MARKER = "::stage "


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
        p = price_for(model)
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
        # The running total, for the status strip. `usd_spent` is otherwise only written
        # when the run finishes, so the strip read $0.0000 for the whole of a ten-minute
        # search and then jumped to the final figure — on the one number the app asks to
        # be trusted with.
        #
        # A marker line on stdout rather than a database write per call: the runner is
        # already reading every line the child prints, so this costs one string, and the
        # child writing the run row mid-run would race the sink that owns it. `_pump`
        # recognises the prefix and keeps it out of the log people read.
        log.info("%s%.6f", SPEND_MARKER, self.spent_usd)
        return cost


# --- prompts ------------------------------------------------------------------

def _preamble(cfg: Config) -> str:
    """Who we are screening for, in their own words.

    This was a hardcoded string — "a nonprofit working across San Diego County and
    Imperial County" — sent for every tenant. `org_name` and `org_location` existed in
    the settings table and reached the dashboard and stopped there. Program fit is 40 of
    the 100 points, so every nonprofit outside San Diego had the largest component of its
    score decided against the wrong region: multi-tenancy reached the database and the UI
    and never reached the prompt. It was the single biggest reason nothing scored well.

    An empty field is passed through as an empty field. "A nonprofit" with no region
    stated is an honest prompt; a guessed region is the thing that broke this.

    **"Be strict" is gone from here**, and its removal is not a tuning preference. It sat
    in the shared preamble, so it biased triage as well as scoring — the cheap binary
    filter that decides what is even worth paying to read. The award floor already does
    that job, deterministically, for free, before any model runs; saying it again in
    English to a model that also has to produce a calibrated 0-100 just drags the whole
    distribution down and compresses it.

    The hours figure is the org's own (`max_effort_hours`) for the same reason the region
    is. It was the constant 10, which is one nonprofit's staffing applied to every tenant,
    and 25 of the 100 points are measured against it.

    `cfg` is required. It was `Config | None` with a fallback per field, which advertised
    a call shape nothing used and let the San Diego default survive in three places.
    """
    org = cfg.org_name.strip()
    where = cfg.org_location.strip()
    hours = cfg.max_effort_hours

    who = f"{org}, a nonprofit" if org else "a nonprofit"
    if where:
        who += f" working in {where}"

    return (
        f"You are screening funding opportunities for {who}.\n"
        "\n"
        "The person reading your output runs this organization. They have one hour on a "
        f"Thursday morning, and about {hours} collective team-hours to spend on any one "
        "application. Their problem is not that they cannot find grants — they can "
        "already find plenty. It is that most of what they find is too small to justify "
        "the hours an application costs.\n"
        "\n"
        "They are looking for funding for these programs, which live in different funder "
        "universes:\n"
    )


def org_context(cfg: Config) -> str:
    """The shared prompt prefix, built from the program cards the user ticked.

    This used to be a hardcoded description of three programs. It is now generated
    from the cards, which is the entire point of making them editable: when they add
    RISE Now or rewrite what RISE Arts is looking for, the model's instructions change
    with it and nobody edits Python.

    Still byte-stable *within* a run — every candidate in a run sees the same prefix —
    so prompt caching behaves exactly as before.
    """
    lines = [_preamble(cfg)]
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
            # An un-filled card is a real state — they added the program but have not
            # described it yet. Say so rather than letting the model invent a remit.
            lines.append("  (No description recorded yet. Judge fit conservatively and "
                         "say in the rationale that this program's card is empty.)")
    return "\n".join(lines) + "\n"

_TRIAGE_RULES = """
Your job is one binary decision: is this page an open funding opportunity that this
organization could actually apply for?

Answer false for: past grantee lists, panelist calls, annual reports, staff pages,
programs open only to individuals rather than organizations, programs restricted to a
kind of applicant this organization is not, and anything already closed.

Answer TRUE when it is a real, open call, even if the page is thin. A page that names no
amount and no deadline is the ordinary case, not a disqualification — this is a yes/no
about whether an application is possible, not about whether it is a good idea. The next
step decides that, and it can only decide it about pages you let through.
"""

_SCORING_RULES = """
Score this opportunity for this organization, write one sentence explaining the score in
language they can act on, and fill in the funder profile they asked for.

You do NOT return a total. You return three components and we add them up, so score each
one on its own and do not adjust one to compensate for another.

  fit_score      0-40   program fit
  award_score    0-35   award size, against their floor
  timing_score   0-25   can this application realistically be finished in time

**Any component you have no evidence for must be null, not zero.**

This is the most important instruction here. A funder that does not publish an award
amount has not offered a small grant — it has published a page that does not mention
money, which is the ordinary case. Scoring that zero says "this is a bad grant" about
every terse funder page on the internet, and it is what made this list unreadable: the
components that go missing are worth 60 of the 100 points, so nothing could ever clear
40. A null takes that component out of the total instead of failing it. Use it freely
and without apology; it costs the opportunity nothing.

  award_score is null   when the page states no award amount, no range and no typical
                        award. Do not estimate one from the funder's size or reputation.
  timing_score is null  when the page gives no deadline and no rolling-basis statement,
                        so there is no calendar to judge the application against.
  fit_score is NEVER null. You always have the page and their programs in front of you,
                        so fit is always answerable — even if the answer is 3.

--- fit_score, 0-40 ---

How well this funder's stated priorities match one of the programs listed above. 40 is a
funder whose own page describes what this organization does. 20 is a plausible but
unstated fit — a general operating funder in their field. 5 is a funder who would have
to stretch. 0 is a different field entirely.

Judge against the programs above and nothing else. If the organization's region is
stated in the preamble, a funder that restricts to somewhere else is a low fit; if no
region is stated, do not assume one and do not penalise a national funder for it.

--- award_score, 0-35, or null ---

Against their floor, which is given below. Use these anchors, and interpolate:

  at the floor          ~10 / 35
  three times the floor ~25 / 35
  ten times the floor   ~35 / 35
  below the floor         0 / 35   (rare — these are usually filtered out before you)

Use the typical or the maximum award, whichever the page actually states; if it states a
range, use the midpoint. A larger award is worth more because the hours cost the same
either way — that is the whole reason this component exists.

--- timing_score, 0-25, or null ---

Judge the application against the deadline, not in the abstract. A grant closing in three
weeks that needs an audited financial statement, three letters of support and a board
resolution is not a 25; a two-page letter of interest due in two months is. A rolling
deadline with a light application is a high score, because there is no calendar pressure
at all. Say so in the rationale when the calendar is the problem.

Nothing else moves the score. In particular:

- Funder warmth is gone. This organization already receives money from the funders it has
  relationships with and does not want to reapply, so a relationship is a reason to
  leave a funder out of the search entirely — never a reason to rank it higher. You are
  not told whether they know a funder, because it must not change the score.

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

INFERRED fields — the three component scores, funder_type, service_areas,
confidence_pct, estimated_effort_hours — are your judgement and are shown to the reader
labelled as such. Use everything on the page. Do not force them: "unknown" and an empty
list are real answers.

The one exception is estimated_effort_hours, which is ALWAYS required. Never leave it
out. Every opportunity on this list gets compared against their hours-per-application
figure, given below with the page, so an application with no estimate cannot be weighed
against one that has it — it silently drops out of the only comparison that matters. If the page is
thin, estimate from what the funder is asking for and how much money is at stake: a
two-page letter of interest is not a full proposal with audited financials. A rough
number you would defend is far more useful to them than no number. If the page is an
index or overview rather than a single application, estimate the typical application it
leads to.

Also:
- deadline_type is "fixed" when the page names one date, "rolling" when it says
  applications are accepted on an ongoing basis or in multiple cycles, and "unknown"
  otherwise. "rolling" needs a quote saying so, same as any sourced field.
- award_typical_stated is what the funder says they TYPICALLY or on AVERAGE award —
  not the maximum, and never a total program budget or a since-inception figure.
- contact_note: only a name, email, or phone number that literally appears on the page.
- confidence_pct is how likely you think it is that this funder would fund one of the
  programs listed above, as a percentage. It is a probability, not a grade: 50 means you
  genuinely think it could go either way. Do not shade it downwards to be cautious — a
  systematically pessimistic number is not more honest than an accurate one, it is just
  wrong in a predictable direction, and this is the largest figure on the row.
- estimated_effort_hours is your read of what a competitive application costs this
  team in WORKING HOURS, counting drafting, gathering attachments, and internal
  review. Give a whole number on every opportunity, without exception — a null cannot
  be compared against their hours figure, so it drops the row out of the only comparison
  that matters instead of failing it. Going over the figure given below is a real signal,
  not a rounding error — say so in the rationale when it happens.
- application_lead_time_days is different and is about the CALENDAR: how many days
  from starting to being able to submit, given what the application requires. Audited
  financials, board resolutions, letters of support and reference forms all depend on
  other people and add weeks that have nothing to do with hours of work. If this
  exceeds the days left before the deadline, the opportunity is not feasible — score
  the "finish in time" component at or near zero and say so plainly in the rationale.
- time_to_funds_days is your estimate of how long AFTER submitting before the money
  would actually reach their bank account — decision timeline plus disbursement. A
  nonprofit's cash flow depends on this and funders rarely state it, so estimate from
  what the page says about review cycles and award dates. This is a judgement, and it
  is labelled as one; null if you have nothing to go on.
- score_rationale is one sentence, no preamble, no hedging, written for someone deciding
  whether to spend a day on this. It must not contain any dollar figure or date that is
  not in the page text above. Do not write "awards are typically around $X" from your own
  knowledge of the funder — a number in this sentence reads as sourced because everything
  around it is, and it is checked against the page.
- needs_human_check is NOT "some information was missing". Missing information is the
  normal case — most funders publish neither an amount nor a deadline — and a component
  you correctly set to null is not a problem to flag. Set it true only when YOU reported
  something you could not fully confirm from the page. Most results should be false.
- If the text you are given is not readable prose — binary, a PDF stream, markup
  fragments — do not score it. Return fit_score 0 with the other two null, say so in the
  rationale, and set needs_human_check true.
"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_opportunity": {
            "type": "boolean",
            "description": "True only if the organization could submit an application to this.",
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


# A hard limit in the structured-outputs API, not a style rule: a schema with more than
# this many union-typed (`["x", "null"]` or anyOf) parameters is refused with a 400 —
# "this causes exponential compilation cost".
#
# It is worth knowing about because it is invisible until a live run. Adding the two
# nullable component scores took this schema to 17 and every scoring call started
# failing; `confidence_pct` and the two contact fields gave the slots back. Nullability
# here is a budget, so spend it on the fields where "the page does not say" is genuinely
# different from a value — and use `""` for the ones where it is not.
MAX_UNION_PARAMS = 16


def union_param_count(schema: dict) -> int:
    """How many of this schema's parameters are union-typed. Tested, not assumed."""
    return sum(1 for spec in schema.get("properties", {}).values()
               if isinstance(spec.get("type"), list) or "anyOf" in spec)


def scoring_schema(program_slugs: list[str]) -> dict:
    """The response schema, with program_match restricted to the ticked programs.

    Built per run rather than hardcoded, because the programs are now editable cards.
    A program the user adds on Sunday has to be selectable by the model on Wednesday
    without anyone editing this file.
    """
    return {
        "type": "object",
        "properties": {
            # The three parts, not a total. The total is composed in Python by
            # `compose_score` so the weights are enforced rather than described, and so a
            # score can be taken apart afterwards — "why is this 38?" used to be
            # unanswerable from the stored data.
            "fit_score": {
                "type": "integer",
                "description": "0-40, program fit. NEVER null — you always have the page "
                               "and their programs, so fit is always answerable.",
            },
            "award_score": {
                "type": ["integer", "null"],
                "description": (
                    "0-35, award size against their floor. NULL when the page states no "
                    "amount, no range and no typical award — a funder that does not "
                    "publish a figure has not offered a small grant. Never estimate one."
                ),
            },
            "timing_score": {
                "type": ["integer", "null"],
                "description": (
                    "0-25, can the application be finished in time. NULL when the page "
                    "gives no deadline and no rolling-basis statement, so there is no "
                    "calendar to judge against."
                ),
            },
            "score_rationale": {"type": "string", "description": "Exactly one sentence."},
            "program_match": {
                "type": "array",
                "items": {"type": "string",
                          "enum": program_slugs or ["NONE"]},
            },
            # Not nullable, unlike every other inferred field. This is an estimate, not
            # a claim about the page, so there is no accuracy rule requiring it to be
            # withheld — and every row is weighed against the org's own hours-per-
            # application figure (`max_effort_hours`), which a null cannot be compared
            # against. Structured outputs enforce the integer, so the model has to commit
            # to a number rather than declining the question.
            "estimated_effort_hours": {
                # NOT nullable, deliberately. The schema used to allow null "if
                # unknowable" and the model took the option on 2 of 5 findings — and a
                # null cannot be compared against their hours figure, so those rows fell
                # out of the decision this whole list exists to serve.
                "type": "integer",
                "description": "Whole WORKING HOURS for a competitive application. Always "
                               "required — estimate from the ask and the award size if the "
                               "page is thin. Never omit or return null.",
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
            # These two are plain strings with "" for absent, not nullable — see
            # MAX_UNION_PARAMS below. `_gated` already treats "" exactly as it treats
            # None, and an empty quote fails `quote_on_page` on length, so nothing about
            # the accuracy gate changes.
            "contact_note": {
                "type": "string",
                "description": (
                    "A contact name, email, or phone number that literally appears on the "
                    'page. "" otherwise — never construct one from a domain name.'
                ),
            },
            "contact_quote": {
                "type": "string",
                "description": 'The exact sentence containing that contact, verbatim. "" if none.',
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
            # Not nullable, for the same reason `estimated_effort_hours` is not: it is
            # the largest figure on the row, and a null cannot be compared against
            # anything — it drops the opportunity out of the comparison rather than
            # failing it. Also buys back a union slot; see MAX_UNION_PARAMS.
            "confidence_pct": {
                "type": "integer",
                "description": "0-100: how likely it is this funder would fund a program "
                               "listed above. A probability, not a grade — 50 means it "
                               "could genuinely go either way.",
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
            "fit_score", "award_score", "timing_score",
            "score_rationale", "program_match", "estimated_effort_hours",
            "application_lead_time_days", "time_to_funds_days",
            "award_min_stated", "award_max_stated", "award_quote",
            "award_typical_stated", "award_typical_quote",
            "deadline_stated", "deadline_quote", "deadline_type", "deadline_type_quote",
            "geography_stated", "geography_quote", "contact_note", "contact_quote",
            "funder_type", "service_areas", "confidence_pct", "needs_human_check",
        ],
        "additionalProperties": False,
    }


# The weights, as data. They were three lines of English inside a prompt and nothing in
# the codebase enforced them, so the "0-100 weighted score" was really one holistic guess
# by the model at a sum it had been described in prose.
WEIGHTS: dict[str, int] = {"fit": 40, "award": 35, "timing": 25}


@dataclass(frozen=True)
class ScoreParts:
    """One score, taken apart. `None` means "there was nothing to judge this on"."""

    fit: int
    award: int | None
    timing: int | None

    @property
    def scored_on(self) -> list[str]:
        return [k for k, v in (("fit", self.fit), ("award", self.award),
                               ("timing", self.timing)) if v is not None]

    @property
    def missing(self) -> list[str]:
        return [k for k in WEIGHTS if k not in self.scored_on]


def compose_score(parts: ScoreParts) -> int:
    """The three components into one 0-100, **renormalised over what was knowable**.

    This is the fix for the thing that made the whole list unreadable.

    The rubric spends 35 points on award size and 25 on whether the application can be
    finished before the deadline. Both need the funder to have published something, and
    `_SCORING_RULES` says plainly that most funders publish neither. So for the median
    candidate 60 of the 100 points were unearnable, every score was really out of 40, and
    the list topped out at 42 — which reads as "we found you nothing good" when what
    actually happened is that grant-makers write terse web pages.

    Scoring a missing component zero is a claim: it says this opportunity was tested on
    award size and failed. It was not tested. Leaving it out of the denominator says the
    true thing instead, and it is the same rule the rest of the app already follows —
    §6's "amount not stated" rather than a guess. We do not invent the number, and we do
    not punish its absence either.

        fit 28/40, award null, timing 9/25
          -> earned 37, available 65, score 57

    A run where nothing is knowable but fit still produces a usable ordering, because fit
    alone is renormalised to 0-100 and candidates are then compared on the one axis every
    one of them has.
    """
    earned = 0
    available = 0
    for key, value in (("fit", parts.fit), ("award", parts.award),
                       ("timing", parts.timing)):
        if value is None:
            continue
        available += WEIGHTS[key]
        earned += max(0, min(WEIGHTS[key], value))
    if available == 0:
        # Cannot happen through `score_one` — fit is non-nullable in the schema — but a
        # zero denominator is not something to discover in production.
        return 0
    return max(0, min(100, round(100 * earned / available)))


def basis_note(parts: ScoreParts) -> str:
    """One sentence saying what a renormalised score was and was not scored on.

    A number that quietly changed its denominator is worse than a low one: 57 out of
    "fit and timing" and 57 out of all three are different claims, and the reader has to
    be told which they are looking at.
    """
    missing = parts.missing
    if not missing:
        return ""
    reason = {
        "award": "the page states no award amount",
        "timing": "the page gives no deadline",
    }
    why = " and ".join(reason.get(m, m) for m in missing)
    dropped = " and ".join(f"{m} ({WEIGHTS[m]} points)" for m in missing)
    return (f"Scored on {' and '.join(parts.scored_on)} only — {why}, "
            f"so {dropped} was not counted for or against it.")


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
           cfg: Config) -> tuple[bool, str]:
    """Binary relevant/not. Cheap model, capped text, no thinking.

    `cfg` is required, and used to be `Config | None = None` falling back to a module
    constant that this change deleted — so the documented call shape was a `NameError`
    waiting for its first caller. The line below already dereferenced `cfg.triage_model`
    unconditionally, so the optional branch could never have worked anyway.
    """
    system = org_context(cfg) + _TRIAGE_RULES
    body = _text_block(
        f"Funder: {candidate.funder}\n"
        f"Page title: {candidate.title}\n"
        f"URL: {candidate.source_url}\n\n"
        f"{candidate.text[:TRIAGE_TEXT_CAP]}"
    )
    model = cfg.triage_model or TRIAGE_MODEL
    budget.check(model, _estimate_tokens(system + body), TRIAGE_MAX_TOKENS)

    resp = _client().messages.create(
        model=api_model(model),
        max_tokens=TRIAGE_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": body}],
        output_config={"format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
    )
    cost = budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
    data = _first_json(resp)
    log.debug("  triage %-40s -> %s (%s) $%.5f",
              candidate.title[:40], data["is_opportunity"], data["reason"], cost)
    return bool(data["is_opportunity"]), str(data["reason"])


# --- tier 3: Sonnet scoring ---------------------------------------------------

def score_one(candidate: RawCandidate, source: Source, cfg: Config,
              budget: Budget) -> Opportunity:
    """Full score + rationale. The system prompt is cached across candidates."""
    system = org_context(cfg) + _SCORING_RULES
    body = _text_block(
        f"Award floor for this run: ${cfg.min_award:,}\n"
        f"Hours they can spend on one application: {cfg.max_effort_hours}\n"
        f"Today: {date.today().isoformat()}\n"
        # The "[WARM — the org has an existing relationship]" hint used to be appended
        # here. Removed with the warmth weight: telling the model about a relationship
        # it must not score on is just an invitation to score on it anyway.
        f"Funder: {candidate.funder}"
        f"\nPage title: {candidate.title}\nURL: {candidate.source_url}\n\n"
        f"{candidate.text[:SCORING_TEXT_CAP]}"
    )
    model = cfg.scoring_model or SCORING_MODEL
    budget.check(model, _estimate_tokens(system + body), SCORING_MAX_TOKENS)

    system_block: dict = {"type": "text", "text": system}
    if _estimate_tokens(system) >= SONNET_CACHE_MIN_TOKENS:
        # Worth caching: the same prompt is reused across every candidate this run.
        system_block["cache_control"] = {"type": "ephemeral"}

    resp = _client().messages.create(
        model=api_model(model),
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
    cost = budget.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
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

    # The same gate, applied to the columns the user added. Each is only kept if its own
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
    # The rationale is prose, so it never passed through the quote gate — and it is the
    # part the user actually reads. A real run produced `award_max = None` (honest) beside
    # a sentence saying "~$80k inferred from public announcements" (not). Flag it and
    # say so on the row rather than silently letting the number stand.
    rationale = str(data["score_rationale"]).strip()
    invented = unsourced_figures(rationale, page_text)
    if invented:
        log.warning("  ⚠ rationale cites unsourced figure(s) %s — flagging",
                    ", ".join(invented))
        rationale = (f"⚠ Mentions {', '.join(invented)}, which is not on the funder's "
                     f"page — check before relying on it. {rationale}")
        needs_check = True

    # Matched nothing and matched everything used to be stored identically: this was
    # `programs or list(active)`, so a candidate the model declined to match against any
    # program was recorded as matching all of them. That is the opposite of what it
    # reported, it puts "For: every program you run" on a row that fits none, and it made
    # program fit impossible to measure — which matters now that fit is a stored number.
    programs = [p for p in (data.get("program_match") or []) if p in active]

    # The three components, composed here rather than trusted as a total. Bounds are
    # applied in `compose_score`; what matters at this level is that null survives as
    # null — coercing it to 0 is exactly the bug being fixed.
    # `fit_score` is required and non-nullable in the schema, so a None here is the model
    # breaking its contract rather than "there was nothing to judge this on". It still has
    # to land as an int — fit is what keeps a run orderable when nothing else is knowable —
    # but it goes through the same helper as the other two rather than the `int(x or 0)`
    # idiom that `_component` exists to keep out of this file.
    fit = _component(data.get("fit_score"))
    parts = ScoreParts(
        fit=0 if fit is None else fit,
        award=_component(data.get("award_score")),
        timing=_component(data.get("timing_score")),
    )
    score = compose_score(parts)
    basis = basis_note(parts)
    if basis:
        rationale = f"{rationale} {basis}".strip()

    opp = Opportunity(
        id=stable_id(candidate.source_url, candidate.title),
        title=candidate.title[:300],
        funder=candidate.funder,
        award_min=award_min,
        award_max=award_max,
        deadline=deadline,
        estimated_effort_hours=data.get("estimated_effort_hours"),
        program_match=programs,
        score=score,
        fit_score=parts.fit,
        award_score=parts.award,
        timing_score=parts.timing,
        score_rationale=rationale,
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


def _component(value) -> int | None:
    """A component score, keeping null as null.

    `int(x or 0)` would turn "there was nothing to judge this on" into "judged, scored
    zero" — which is the exact confusion this whole change exists to remove, so it gets
    its own named function rather than an inline expression somebody can simplify.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded(value, ceiling: int) -> int | None:
    """A day count that survives being wrong. A model that answers 99999 should give us
    nothing rather than a number the UI renders as fact."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= ceiling else None


def _as_enum(enum_cls, raw, default):
    try:
        return enum_cls(str(raw))
    except (ValueError, TypeError):
        return default
