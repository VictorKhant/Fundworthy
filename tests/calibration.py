"""The calibration test. (CLAUDE.md)

    "tests/calibration.py holds five opportunities the user says are a clear yes and
     five they say are a clear no. The scoring model must rank all five yeses above
     all five noes. This is the only test that matters."

⚠️  THE FIXTURES BELOW ARE NOT MAURI'S.  ⚠️

She has not supplied them yet — see FUTURE.md. They are placeholders
written from the criteria stated in CLAUDE.md and §7, so the harness is real and
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
from dataclasses import dataclass, replace
from datetime import date, timedelta

from agent.config import Config, ProgramCard
from agent.evalmetrics import report
from agent.filters import apply_filters
from agent.models import Program
from agent.parse import parse_page
from agent.score import Budget, BudgetExceeded, score_one
from agent.sources import Confidence, Source, Tier

# Flip to True only when the ten fixtures below are the ones the user actually gave us.
FIXTURES_ARE_FROM_MAURI = False

REJECTED_SCORE = -1  # a candidate the free filters killed never reaches the model


def _in(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime("%B %d, %Y")


# Described program cards, because `Config()`'s defaults are three EMPTY ones.
#
# That is not a detail. An undescribed card makes `org_context` emit "(No description
# recorded yet. Judge fit conservatively and say in the rationale that this program's
# card is empty.)" — so every run of this harness was measuring program fit, the
# 40-point component, against nothing at all, and two rationales in the first live run
# said so out loud. An eval that runs the product in a state no real org would use
# cannot calibrate it.
CALIBRATION_PROGRAMS = [
    ProgramCard(
        slug="RULFP", name="RISE Urban Leadership Fellows Program",
        summary="A cohort fellowship developing the next generation of BIPOC community "
                "leaders in San Diego County.",
        what_it_funds="Fellow stipends, cohort facilitation, and staff time.",
        keywords=["BIPOC leadership development", "cohort fellowship",
                  "civic engagement", "community leadership"],
    ),
    ProgramCard(
        slug="RESILIENCE", name="RISE Resilience & Renewal",
        summary="Addresses burnout and retention among nonprofit leaders of colour "
                "through whole-person wellbeing support.",
        what_it_funds="Facilitation, sabbatical support, and mental health provision.",
        keywords=["nonprofit leader burnout", "workforce retention",
                  "health equity", "leader wellbeing"],
    ),
    ProgramCard(
        slug="ARTS", name="RISE Arts",
        summary="Community arts programming rooted in cultural equity and creative "
                "placemaking in historically marginalized neighbourhoods.",
        what_it_funds="Teaching artists, materials, and venue costs.",
        keywords=["cultural equity", "creative placemaking", "community arts",
                  "arts and social justice"],
    ),
]


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

# --- the terse ones, which are what production actually looks like -------------
#
# Every fixture above states an award amount AND a deadline. All ten of them. The real
# database, at the time this was written, held eight findings of which exactly one stated
# an award — so the golden set was drawn from very nearly the opposite of the input
# distribution, and the harness was blind to the failure that mattered most.
#
# That failure: the rubric spent 35 points on award size and 25 on finishing before a
# deadline, both of which need the funder to have published something. On a terse page
# neither is earnable, so scores collapsed toward 40 and the list stopped discriminating.
# With fixtures that all carry an amount, nothing here could ever see it.
#
# So these five exist to test the case the product mostly meets: a page with real prose
# and no numbers on it. The pair that matters is `yes-terse-fit` against
# `no-terse-wrong-field` — identical evidence poverty, opposite program fit. If the
# ranking cannot separate those two it cannot rank a normal week.
#
# They need to clear `_is_thin_landing_page` (1200 characters with no amount and no
# deadline), which is realistic: a funder page with nothing on it is genuinely a nav page.

_FILLER_GOOD = (
    "Our grantmaking is guided by the communities we serve. We believe the "
    "organizations closest to a problem are best placed to solve it, and our role is to "
    "move resources to them with as little friction as we can manage. We review "
    "proposals on an ongoing basis and staff are available to talk through an idea "
    "before anything is written down. Reporting is a short conversation and a one-page "
    "summary; we do not require audited financial statements from organizations below a "
    "certain size, and we do not require a match. We fund general operating support "
    "wherever we can, because we have heard consistently from our partners that "
    "restricted project funding creates administrative work out of proportion to its "
    "value. Our board meets quarterly and decisions are communicated within two weeks of "
    "each meeting. We are a small team and we try to answer every enquiry. If your work "
    "is a fit for the priorities described above we would rather hear from you early "
    "than receive a polished proposal that we have to decline. We publish our grantee "
    "list annually and encourage prospective applicants to look at who we have funded "
    "before, as it is often the clearest statement of what we are interested in. "
)

YES += [
    Fixture(
        label="yes-terse-fit",
        funder="Coastal Community Trust",
        title="Leadership and Civic Participation — Grantmaking Priorities",
        programs=(Program.RULFP,),
        body=(
            "The Trust funds nonprofit organizations across San Diego County that build "
            "leadership among Black, Indigenous and people of colour, with a particular "
            "interest in cohort-based fellowship models and resident-led civic "
            "engagement. We support organizations developing the next generation of "
            "community leaders. " + _FILLER_GOOD
        ),
    ),
    Fixture(
        label="yes-terse-arts",
        funder="Harbor Arts Endowment",
        title="What We Fund — Arts and Cultural Equity",
        programs=(Program.ARTS,),
        body=(
            "The Endowment supports arts organizations in Southern California whose work "
            "advances cultural equity and creative placemaking, especially those led by "
            "and serving historically marginalized communities. " + _FILLER_GOOD
        ),
    ),
]

NO_TERSE = [
    Fixture(
        label="no-terse-wrong-field",
        funder="Peninsula Veterinary Science Foundation",
        title="Research Funding — Companion Animal Health",
        programs=(Program.RULFP,),
        body=(
            "The Foundation funds veterinary teaching hospitals and accredited "
            "laboratories conducting research into companion animal oncology, "
            "orthopaedics and infectious disease. Applicants must hold a current "
            "research licence and be affiliated with a veterinary school. " + _FILLER_GOOD
        ),
    ),
    Fixture(
        label="no-terse-individuals-only",
        funder="Marchetti Fellowship Fund",
        title="Fellowships for Individual Scholars",
        programs=(Program.RULFP,),
        body=(
            "The Fund makes awards to individual doctoral candidates and postdoctoral "
            "scholars in the history of science. Awards are made to named individuals and "
            "cannot be held by an organization; institutional overhead is not paid and "
            "nonprofit organizations are not eligible to apply. " + _FILLER_GOOD
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

NO += NO_TERSE


# --- harness ------------------------------------------------------------------

@dataclass
class Outcome:
    fixture: Fixture
    expected: str          # "YES" | "NO"
    score: int
    rationale: str
    killed_by: str | None = None
    # The three components the total was composed from, kept because the failure text at
    # the bottom of this file tells the reader to look at them — "a low component is a
    # prompt problem; a low TOTAL with healthy components is a composition problem" — and
    # they were dropped on the floor at the `score_one` call, so the one diagnostic the
    # harness promises was the one thing it did not print. None means not scored.
    fit: int | None = None
    award: int | None = None
    timing: int | None = None

    @property
    def parts(self) -> str:
        """`60/30/10` with a dash for a component the page gave nothing to judge."""
        if self.fit is None and self.award is None and self.timing is None:
            return ""
        cell = lambda v: "—" if v is None else str(v)  # noqa: E731
        return f"{cell(self.fit)}/{cell(self.award)}/{cell(self.timing)}"

    @property
    def line(self) -> str:
        shown = "REJECTED" if self.score == REJECTED_SCORE else f"{self.score:>3}"
        why = self.killed_by or self.rationale
        return (f"  {self.expected:<3}  {shown:>8}  {self.parts:>9}  "
                f"{self.fixture.funder[:32]:<32}  {why[:56]}")


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
    return Outcome(fixture, expected, opp.score, opp.score_rationale,
                   fit=opp.fit_score, award=opp.award_score, timing=opp.timing_score)


def main() -> int:
    p = argparse.ArgumentParser(description="the organization's scoring calibration")
    p.add_argument("--dry-run", action="store_true",
                   help="filters only — no API calls, $0.00")
    p.add_argument("--budget", type=float, default=1.00)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # The fixtures below are San Diego shaped, so the org has to be too. Leaving this
    # blank would have the harness screen them as "a nonprofit" with no region — a
    # fair test of a different thing, and it would quietly hide a regression in the
    # geography half of program fit.
    cfg = Config(org_name="Rise San Diego",
                 org_location="San Diego and Imperial County, California",
                 programs=CALIBRATION_PROGRAMS)
    budget = Budget(ceiling_usd=args.budget)

    print("=" * 88)
    print("CALIBRATION — CLAUDE.md")
    print("=" * 88)
    if not FIXTURES_ARE_FROM_MAURI:
        print(
            "\n  ⚠️  THESE FIXTURES ARE NOT MAURI'S.\n"
            "     They are placeholders derived from CLAUDE.md and §7 so the harness\n"
            "     runs today. A PASS HERE DOES NOT MEAN THE MODEL IS CALIBRATED — it means\n"
            "     the pipeline can rank. See FUTURE.md.\n"
        )
    print(f"  Screening for: {cfg.org_name} — {cfg.org_location}")
    print(f"  Award floor ${cfg.min_award:,} · {cfg.max_effort_hours}h per application.\n")

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

    print("  exp     score   fit/awd/tm  funder                            why")
    print("  " + "-" * 92)
    for o in outcomes:
        print(o.line)

    yes_scores = [o.score for o in outcomes if o.expected == "YES"]
    no_scores = [o.score for o in outcomes if o.expected == "NO"]
    print(f"\n  cost: ${budget.spent_usd:.4f} over {budget.calls} calls")

    if args.dry_run:
        wrongly_killed = [o for o in outcomes if o.expected == "YES" and o.killed_by]
        survived = [o for o in outcomes if o.expected == "NO" and not o.killed_by]
        print(f"\n  --dry-run: filters killed "
              f"{len([o for o in outcomes if o.killed_by])}/{len(outcomes)}")
        if wrongly_killed:
            print("  ✗ FAIL — a clear YES was killed by a free filter:")
            for o in wrongly_killed:
                print(f"      {o.fixture.funder}: {o.killed_by}")
            return 1
        print(f"  ✓ no YES was wrongly filtered; {len(survived)} NO(s) left for the model")
        return 0

    # Four questions, not one. This used to assert only that every YES outranked every
    # NO — and that assertion was blind to the failure we actually shipped: eight
    # findings scoring 13-42, six of them inside a seven-point band. Separation was fine.
    # The list was useless. See agent/evalmetrics.py.
    # Ordering is judged on everything, because a NO the free filters killed IS correctly
    # ranked below every YES and it would be dishonest to drop it. The SPREAD is judged
    # on scored rows only: a -1 sentinel for "never reached the model" is not a score, and
    # leaving it in inflated the range to "-1-57" and made a compressed distribution look
    # healthy — the exact illusion these metrics exist to remove.
    scored_no = [s for s in no_scores if s != REJECTED_SCORE]
    filtered = len(no_scores) - len(scored_no)

    card = report(yes_scores, no_scores)
    scale = report(yes_scores, scored_no)

    # One report to print and a different one to judge is how a run prints "ordering 100%"
    # and then fails on ordering: `scale` drops the filtered NOs, which can only lower its
    # pair accuracy, and it was `scale.failures()` that decided the verdict. Compose the
    # report the paragraph above describes instead — ordering from everything, spread from
    # the rows a model actually scored — so the numbers on screen are the ones being
    # tested against.
    judged = replace(scale, pair_accuracy=card.pair_accuracy, separation=card.separation)

    print()
    print(f"  ordering     {judged.pair_accuracy:.0%} of good/bad pairs correct "
          f"(AUC) · separation {judged.separation:+.0f}")
    print(f"  agreement    {card.rank_agreement:+.2f} rank correlation "
          f"(binary labels cap this below 1.0)")
    print(f"  spread YES   {scale.yes}")
    print(f"  spread NO    {scale.no}"
          f"{f'  (+{filtered} killed by free filters, never scored)' if filtered else ''}")
    print(f"  spread all   {scale.overall}")

    problems = judged.failures()
    if not problems:
        verdict = "✓ PASS — ranked correctly, and the scale is being used."
        if not FIXTURES_ARE_FROM_MAURI:
            verdict += "\n    (On placeholder fixtures. Not yet evidence of calibration.)"
        print(f"\n  {verdict}\n")
        return 0

    print("\n  ✗ FAIL")
    for problem in problems:
        print(f"      • {problem}")

    worst_yes, best_no = min(yes_scores), max(no_scores)
    overlapping = [o for o in outcomes
                   if (o.expected == "YES" and o.score <= best_no)
                   or (o.expected == "NO" and o.score >= worst_yes)]
    if overlapping:
        print("\n  Overlapping cases:")
        for o in overlapping:
            print(f"      [{o.expected}] {o.score:>3}  {o.fixture.funder}: "
                  f"{o.rationale[:60]}")
    print("\n  The score is composed in agent/score.py: compose_score from three "
          "components\n  the model returns separately. A low component is a prompt "
          "problem; a low TOTAL\n  with healthy components is a composition problem.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
