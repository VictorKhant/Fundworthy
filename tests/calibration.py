"""The calibration test. (CLAUDE.md §10)

    "tests/calibration.py holds five opportunities Mauri says are a clear yes and
     five she says are a clear no. The scoring model must rank all five yeses above
     all five noes. This is the only test that matters."

⚠️  THE FIXTURES BELOW ARE NOT MAURI'S.  ⚠️

She has not supplied them yet — see STAKEHOLDER.md question 8. They are placeholders
written from the criteria stated in CLAUDE.md §1 and §7, so the harness is real and
runnable today. **A pass here does not mean the model is calibrated.** It means the
pipeline can rank, and the plumbing works. The test says so on every run, loudly,
and refuses to report success without that caveat.

Replace the fixtures, flip FIXTURES_ARE_FROM_MAURI to True, and the run stops
disclaiming itself.

    python -m tests.calibration --dry-run   # filters only, no API calls, $0.00
    python -m tests.calibration             # full pipeline, needs ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from agent.config import Config
from agent.filters import apply_filters
from agent.models import Program
from agent.parse import parse_page
from agent.score import Budget, BudgetExceeded, score_one
from agent.sources import Confidence, Source, Tier

# Flip to True only when the ten fixtures below are the ones Mauri actually gave us.
FIXTURES_ARE_FROM_MAURI = False

REJECTED_SCORE = -1  # a candidate the free filters killed never reaches the model


def _in(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime("%B %d, %Y")


@dataclass
class Fixture:
    label: str
    funder: str
    title: str
    body: str
    warm: bool = False
    programs: tuple[Program, ...] = ()

    def as_source(self) -> Source:
        return Source(
            name=self.funder,
            funder=self.funder,
            url=f"https://example.invalid/{self.label}",
            tier=Tier.WARM if self.warm else Tier.INTERMEDIARY,
            programs=list(self.programs),
            confidence=Confidence.CONFIRMED,
            warm=self.warm,
        )

    def as_html(self) -> str:
        return f"<html><head><title>{self.title}</title></head><body>{self.body}</body></html>"


# --- five clear YES -----------------------------------------------------------

YES: list[Fixture] = [
    Fixture(
        label="yes-ahf-i2",
        funder="Alliance Healthcare Foundation",
        title="Innovation Initiative (i2) Challenge — 2026 Open Call",
        warm=True,
        programs=(Program.RESILIENCE,),
        body=(
            f"Applications are due {_in(75)}. Grants of up to $150,000 are awarded to "
            "San Diego and Imperial County nonprofits addressing health equity. This "
            "cycle prioritizes nonprofit leader burnout, workforce retention, and "
            "whole-body approaches to leader wellbeing. A short letter of interest is "
            "the only first-round requirement. No match is required."
        ),
    ),
    Fixture(
        label="yes-sdf-leadership",
        funder="San Diego Foundation",
        title="Community Leadership Fund — Resident-Led Civic Engagement",
        warm=True,
        programs=(Program.RULFP,),
        body=(
            f"Deadline: {_in(60)}. Awards range from $75,000 to $200,000 over two years "
            "for organizations building BIPOC leadership pipelines in San Diego County. "
            "General operating support. Cohort fellowship models are explicitly "
            "encouraged. Application is a six-page narrative."
        ),
    ),
    Fixture(
        label="yes-cac-arts-justice",
        funder="California Arts Council",
        title="Arts and Social Justice — Statewide Program",
        warm=True,
        programs=(Program.ARTS,),
        body=(
            f"Applications close {_in(45)}. Grants of up to $100,000 support arts "
            "organizations led by and serving historically marginalized communities "
            "across California. Cultural equity and creative placemaking are core "
            "criteria. Multi-year renewable."
        ),
    ),
    Fixture(
        label="yes-prebys-leadership",
        funder="Prebys Foundation",
        title="2026 Prebys Leadership Awards",
        warm=True,
        programs=(Program.RULFP,),
        body=(
            f"Nominations are due {_in(90)}. The award provides up to $250,000 per "
            "grantee in unrestricted funding to San Diego County nonprofit leaders "
            "advancing adaptive leadership and community capacity. Nomination is a "
            "two-page form."
        ),
    ),
    Fixture(
        label="yes-city-arts-culture",
        funder="City of San Diego Commission for Arts and Culture",
        title="Organizational Support Program — FY2027",
        warm=True,
        programs=(Program.ARTS,),
        body=(
            f"The deadline to apply is {_in(55)}. Awards range from $60,000 to "
            "$180,000 for San Diego arts organizations. Funding is unrestricted "
            "operating support based on a formula. No match required."
        ),
    ),
]

# --- five clear NO ------------------------------------------------------------

NO: list[Fixture] = [
    Fixture(
        label="no-too-small",
        funder="Small Community Fund of San Diego",
        title="Neighborhood Micro-Grant Program",
        programs=(Program.RULFP,),
        body=(
            f"Applications due {_in(50)}. Grants of up to $2,500 support small "
            "neighborhood projects in San Diego County. Requires a detailed budget, "
            "three letters of support, and quarterly reporting."
        ),
    ),
    Fixture(
        label="no-religious",
        funder="Evangelical Christian Ministry Foundation",
        title="Faith Community Leadership Grants",
        programs=(Program.RULFP,),
        body=(
            f"Deadline {_in(70)}. Awards of up to $120,000 to church-affiliated "
            "organizations developing congregation leadership in Southern California."
        ),
    ),
    Fixture(
        label="no-wrong-geography",
        funder="Great Lakes Regional Foundation",
        title="Urban Leadership Initiative",
        programs=(Program.RULFP,),
        body=(
            f"Applications due {_in(65)}. Grants of up to $300,000 for BIPOC "
            "leadership development. Eligibility is limited to organizations in "
            "Michigan, Ohio, and Illinois."
        ),
    ),
    Fixture(
        label="no-deadline-too-soon",
        funder="Regional Wellness Collaborative",
        title="Rapid Response Wellness Grants",
        programs=(Program.RESILIENCE,),
        body=(
            f"Applications must be submitted by {_in(5)}. Awards of up to $90,000 for "
            "San Diego County nonprofits addressing staff burnout. Full proposal, "
            "audited financials, and board resolution required."
        ),
    ),
    Fixture(
        label="no-not-an-opportunity",
        funder="California Arts Council",
        title="CALL FOR PANELISTS — FY2027 Grant Review",
        programs=(Program.ARTS,),
        body=(
            "The Council seeks arts professionals to serve on grant review panels. "
            "Panelists receive a $500 honorarium per review cycle. This is not a "
            "funding opportunity for organizations."
        ),
    ),
]


# --- harness ------------------------------------------------------------------

@dataclass
class Outcome:
    fixture: Fixture
    expected: str          # "YES" | "NO"
    score: int
    rationale: str
    killed_by: str | None = None

    @property
    def line(self) -> str:
        shown = "REJECTED" if self.score == REJECTED_SCORE else f"{self.score:>3}"
        why = self.killed_by or self.rationale
        return f"  {self.expected:<3}  {shown:>8}  {self.fixture.funder[:32]:<32}  {why[:70]}"


def evaluate(fixture: Fixture, expected: str, cfg: Config,
             budget: Budget, dry_run: bool) -> Outcome:
    source = fixture.as_source()
    page = parse_page(source.url, fixture.as_html())

    verdict = apply_filters(page, fixture.funder, cfg)
    if verdict.rejected:
        return Outcome(fixture, expected, REJECTED_SCORE, "",
                       killed_by=f"filter: {verdict.reason.value} ({verdict.detail})")

    if dry_run:
        return Outcome(fixture, expected, 0, "(--dry-run: not scored)")

    from agent.parse import to_candidate

    candidate = to_candidate(page, fixture.funder, int(source.tier), list(fixture.programs))
    opp = score_one(candidate, source, cfg, budget)
    return Outcome(fixture, expected, opp.score, opp.score_rationale)


def main() -> int:
    p = argparse.ArgumentParser(description="RISE scoring calibration")
    p.add_argument("--dry-run", action="store_true",
                   help="filters only — no API calls, $0.00")
    p.add_argument("--budget", type=float, default=1.00)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    cfg = Config()
    budget = Budget(ceiling_usd=args.budget)

    print("=" * 88)
    print("CALIBRATION — CLAUDE.md §10")
    print("=" * 88)
    if not FIXTURES_ARE_FROM_MAURI:
        print(
            "\n  ⚠️  THESE FIXTURES ARE NOT MAURI'S.\n"
            "     They are placeholders derived from CLAUDE.md §1 and §7 so the harness\n"
            "     runs today. A PASS HERE DOES NOT MEAN THE MODEL IS CALIBRATED — it means\n"
            "     the pipeline can rank. See STAKEHOLDER.md question 8.\n"
        )
    print(f"  Award floor for this run: ${cfg.min_award:,} (§11 Q1, answered).\n")

    outcomes: list[Outcome] = []
    try:
        for fx in YES:
            outcomes.append(evaluate(fx, "YES", cfg, budget, args.dry_run))
        for fx in NO:
            outcomes.append(evaluate(fx, "NO", cfg, budget, args.dry_run))
    except BudgetExceeded as exc:
        print(f"\n  BUDGET CEILING HIT — {exc}")
        print("  Calibration incomplete. Raise --budget or reduce the fixture set.\n")
        return 2

    print("  exp     score  funder                            why")
    print("  " + "-" * 84)
    for o in outcomes:
        print(o.line)

    yes_scores = [o.score for o in outcomes if o.expected == "YES"]
    no_scores = [o.score for o in outcomes if o.expected == "NO"]
    print(f"\n  cost: ${budget.spent_usd:.4f} over {budget.calls} calls")

    if args.dry_run:
        wrongly_killed = [o for o in outcomes if o.expected == "YES" and o.killed_by]
        survived = [o for o in outcomes if o.expected == "NO" and not o.killed_by]
        print(f"\n  --dry-run: filters killed {len([o for o in outcomes if o.killed_by])}/10")
        if wrongly_killed:
            print("  ✗ FAIL — a clear YES was killed by a free filter:")
            for o in wrongly_killed:
                print(f"      {o.fixture.funder}: {o.killed_by}")
            return 1
        print(f"  ✓ no YES was wrongly filtered; {len(survived)} NO(s) left for the model")
        return 0

    worst_yes, best_no = min(yes_scores), max(no_scores)
    print(f"  lowest YES = {worst_yes}   highest NO = {best_no}")

    if worst_yes > best_no:
        verdict = "✓ PASS — every YES ranks above every NO."
        if not FIXTURES_ARE_FROM_MAURI:
            verdict += "\n    (On placeholder fixtures. Not yet evidence of calibration.)"
        print(f"\n  {verdict}\n")
        return 0

    print(f"\n  ✗ FAIL — separation is {worst_yes - best_no}. Overlapping cases:")
    for o in outcomes:
        if (o.expected == "YES" and o.score <= best_no) or \
           (o.expected == "NO" and o.score >= worst_yes):
            print(f"      [{o.expected}] {o.score:>3}  {o.fixture.funder}: {o.rationale[:60]}")
    print("  Adjust the weights in agent/score.py SCORING_SYSTEM and re-run.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
