"""The golden-fixture accuracy harness: real funder pages, real test organizations,
and hand-labelled ground truth — "does the pipeline agree with what a human reading
the page sees" as an assertion, not a vibe.

This is what tests/calibration.py's own docstring says it is NOT: real HTML, not
synthetic prose fixtures, and expectations established by reading the actual fetched
page (see tests/fixtures/manifest.py) rather than by running the pipeline and copying
its output. Grew directly out of the product owner's own bug reports — "sometimes the
deadline didn't fetch", "sometimes closed grants show as open" — tested against real
pages from the shipped funder registry rather than invented cases, then expanded to
four real program cards spanning two organizations (New Destiny Housing's HASS; RISE
San Diego's ARTS/RULFP/RESILIENCE) so a page's relevance to one program and its
irrelevance to another are both exercised on the same real fetch, not assumed.

**What this file can and cannot check offline.** Stage 1 — fetch, parse, the free
deterministic filters — needs no model and no key, so every fixture's stage-1 verdict
is asserted directly and runs in CI on every change. Stages 2 and 3 need a real
Anthropic key the same way tests/calibration.py's full run does; this file records what
SHOULD happen there (tests/fixtures/manifest.py: expect_actionable, expect_relevant,
reasoning) as a written, checkable prediction, but does not and cannot verify it here.
Run the live check with a key:

    python3 -m tests.test_golden_fixtures --live   # needs ANTHROPIC_API_KEY, ~$0.30

**Recall, precision, accuracy — not just an agreement count.** `_TRIAGE_RULES` asks one
combined yes/no per candidate: "is this page an open funding opportunity that this
organization could actually apply for". The ground truth for that question, per
(fixture, org), is `expect_actionable AND <relevant to at least one of the org's active
programs>` — computed from the two SEPARATE axes tests/fixtures/manifest.py records, so
the live check can score real true/false positives and negatives instead of a single
hand-merged guess. Two organizations are run against the full fixture set: New Destiny
Housing (its one program, HASS) and RISE San Diego (all three of ARTS/RULFP/RESILIENCE
active at once, the way a real multi-program org actually runs a search) — mirroring
how `agent/score.py: triage()` is actually called in production, against every active
program card in a single prompt, not one program in isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import Config, ProgramCard  # noqa: E402
from agent.filters import Reject, apply_filters  # noqa: E402
from agent.parse import parse_page  # noqa: E402
from tests.fixtures.manifest import (  # noqa: E402
    FIXTURES, ORG_FOR_PROGRAM, PROGRAMS, PageFixture,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pages"

# The two organizations this fixture set is judged against. "hass" alone (New Destiny
# Housing, a single-program org) and the three RISE San Diego cards together (a
# multi-program org, which is the shape most real Fundworthy accounts actually take —
# CLAUDE.md §2 seeds RULFP/RESILIENCE/ARTS as the shipped defaults).
_ORG_PROGRAM_GROUPS: dict[str, list[str]] = {
    "New Destiny Housing": ["hass"],
    "RISE San Diego": ["ARTS", "RULFP", "RESILIENCE"],
}


def _config_for(org_name: str, program_slugs: list[str]) -> Config:
    _name, location = ORG_FOR_PROGRAM[program_slugs[0]]
    cards = [
        ProgramCard(
            slug=slug,
            name=PROGRAMS[slug]["name"],
            summary=PROGRAMS[slug]["summary"],
            what_it_funds=PROGRAMS[slug]["what_it_funds"],
            keywords=list(PROGRAMS[slug]["keywords"]),
        )
        for slug in program_slugs
    ]
    return Config(org_name=org_name, org_location=location, programs=cards)


def _housing_config() -> Config:
    return _config_for("New Destiny Housing", ["hass"])


def _load(fx: PageFixture):
    html = (FIXTURES_DIR / f"{fx.slug}.html").read_text(encoding="utf-8", errors="replace")
    page = parse_page(fx.url, html)
    verdict = apply_filters(page, fx.funder, _housing_config())
    return page, verdict


@pytest.mark.parametrize("fx", FIXTURES, ids=lambda f: f.slug)
def test_stage_one_verdict_matches_a_human_reading_the_real_page(fx: PageFixture):
    _page, verdict = _load(fx)
    assert verdict.rejected == fx.expect_rejected, (
        f"{fx.slug}: expected rejected={fx.expect_rejected}, got {verdict.rejected} "
        f"({verdict.reason}, {verdict.detail!r}) — {fx.note}"
    )
    if fx.expect_reject_reason is not None:
        assert verdict.reason is not None
        assert verdict.reason.value == fx.expect_reject_reason, (
            f"{fx.slug}: expected reject reason {fx.expect_reject_reason!r}, "
            f"got {verdict.reason.value!r}"
        )


@pytest.mark.parametrize(
    "fx", [f for f in FIXTURES if f.expect_award_max is not None], ids=lambda f: f.slug,
)
def test_the_real_award_figure_is_extracted_correctly(fx: PageFixture):
    page, _verdict = _load(fx)
    assert page.award_max == fx.expect_award_max, (
        f"{fx.slug}: expected award_max={fx.expect_award_max}, got {page.award_max} "
        f"— {fx.note}"
    )


@pytest.mark.parametrize(
    "fx", [f for f in FIXTURES if f.expect_deadline is not None], ids=lambda f: f.slug,
)
def test_a_real_future_deadline_is_extracted_correctly(fx: PageFixture):
    """Every other fixture with a stated deadline states one that has already passed
    (asserted via the three pinned closed-grant tests below, against `verdict.detail`).
    `port-sd-tap` is this set's one real, currently-open deadline, so
    `ParsedPage.earliest_deadline` on a genuinely future date is checked end to end
    here rather than only via the synthetic cases in
    tests/test_deadline_amount_extraction.py."""
    page, _verdict = _load(fx)
    assert page.earliest_deadline == fx.expect_deadline, (
        f"{fx.slug}: expected earliest_deadline={fx.expect_deadline}, got "
        f"{page.earliest_deadline} — {fx.note}"
    )


@pytest.mark.parametrize(
    "fx", [f for f in FIXTURES if f.expect_has_apply_url is not None], ids=lambda f: f.slug,
)
def test_apply_url_presence_matches_expectation(fx: PageFixture):
    page, _verdict = _load(fx)
    assert bool(page.apply_url) == fx.expect_has_apply_url, (
        f"{fx.slug}: expected an apply_url={'yes' if fx.expect_has_apply_url else 'no'}, "
        f"got {page.apply_url!r} — {fx.note}"
    )


# --- the real bugs this fixture set specifically exists to pin down --------------

def test_hilton_foundations_past_grant_record_is_not_read_as_an_open_award():
    """The $2.4M figure on this real page is a past, already-disbursed grant (labelled
    'Awarded Date: August, 2022' a few lines below it) — not an open call's award
    range. Extracting it as one would tell a nonprofit that clearing Hilton's floor
    means qualifying for $2.4M, which is not a claim this page makes about anyone
    applying today."""
    fx = next(f for f in FIXTURES if f.slug == "hilton_foundation")
    page, _ = _load(fx)
    assert page.award_max is None


def test_hearst_healths_stated_floor_is_not_read_as_the_award_ceiling():
    """The one dollar figure on this real page is 'Minimum grant size is $100,000' —
    a floor, not a ceiling. `award_max` and `award_min` used to both resolve to the
    same min()/max() over one evidence value, so the stated floor was reported as the
    cap. `award_min` is unaffected and should still correctly resolve to 100_000."""
    fx = next(f for f in FIXTURES if f.slug == "hearst_health")
    page, _ = _load(fx)
    assert page.award_max is None, (
        f"a stated MINIMUM was reported as the award ceiling: {page.award_max}"
    )
    assert page.award_min == 100_000


def test_sd_prides_open_date_is_not_confused_with_its_real_deadline():
    """This page states BOTH an open date (Oct 6, 2025) and the real deadline
    (Nov 3, 2025) in one run-on sentence, with the words 'Applications open' directly
    in front of the open date and 'Deadline to apply' directly in front of the real
    one. Rejecting on the wrong one would not just be imprecise — it would tell the
    org this grant closed three and a half weeks earlier than it actually did."""
    fx = next(f for f in FIXTURES if f.slug == "sdpride-grants")
    _page, verdict = _load(fx)
    assert verdict.detail == "2025-11-03", (
        f"rejected on the wrong date: {verdict.detail!r} (expected the real deadline, "
        f"not the open date one sentence earlier)"
    )


def test_a_two_digit_year_deadline_is_not_off_by_a_century():
    """CalVIP's real page states 'Proposals due 6/27/25' — parsed as the year 2125 by
    a real bug in this pipeline before it was fixed, which is a hundred years, not a
    typo. Locked here against the real page it was found on, not just a synthetic
    string (tests/test_deadline_amount_extraction.py has that version)."""
    fx = next(f for f in FIXTURES if f.slug == "bscc-calvip")
    _page, verdict = _load(fx)
    assert verdict.detail == "2025-06-27"
    assert "2125" not in verdict.detail


# --- the golden-fixture set has both YES and NO cases, or it proves nothing ------

def test_the_fixture_set_actually_spans_both_outcomes():
    """A harness where every fixture passes (or every fixture fails) cannot catch a
    regression in the branch it never exercises. This is the same principle CLAUDE.md
    applies to the calibration harness itself."""
    rejected = [f for f in FIXTURES if f.expect_rejected]
    passed = [f for f in FIXTURES if not f.expect_rejected]
    assert len(rejected) >= 3, "not enough real reject cases to catch a regression"
    assert len(passed) >= 3, "not enough real pass cases to catch a regression"
    # And the rejects are not all the same reason — that would only prove one branch.
    reasons = {f.expect_reject_reason for f in rejected}
    assert reasons, "rejected fixtures must each name a specific reason"


def test_relevance_ground_truth_spans_both_outcomes_per_program():
    """The same principle, applied to the live-check ground truth rather than the
    offline stage-1 verdict: a program with every fixture marked relevant (or every
    fixture marked irrelevant) could never catch the live model getting it backwards,
    because there is no disagreeing case in the set to catch it on."""
    for slug in PROGRAMS:
        values = [f.expect_relevant[slug] for f in FIXTURES
                 if f.expect_relevant.get(slug) is not None]
        assert True in values, f"{slug}: no fixture asserts relevant=True"
        assert False in values, f"{slug}: no fixture asserts relevant=False"


def test_every_fixture_file_referenced_by_the_manifest_actually_exists():
    """The manifest and the HTML directory can drift — a fixture renamed or deleted
    on one side and not the other silently stops testing anything."""
    for fx in FIXTURES:
        path = FIXTURES_DIR / f"{fx.slug}.html"
        assert path.exists(), f"{fx.slug}: manifest references a missing fixture file"
        assert path.stat().st_size > 1000, f"{fx.slug}: fixture file looks truncated"


# --- the live extension: needs a key, not run by pytest --------------------------

def _expected_triage(fx: PageFixture, program_slugs: list[str]) -> bool | None:
    """Ground truth for one (fixture, org) pair, or None if not enough of the
    manifest is asserted to compute it. `_TRIAGE_RULES` asks one combined question —
    is this page an open opportunity this org could apply for — so the expected
    answer is actionable AND relevant to at least one of the org's active programs,
    exactly mirroring how `triage()` is actually called: once per candidate, against
    every active program card in a single prompt."""
    if fx.expect_actionable is None:
        return None
    if not fx.expect_actionable:
        return False
    values = [fx.expect_relevant[s] for s in program_slugs if fx.expect_relevant.get(s) is not None]
    if not values:
        return None
    return any(values)


def _live_check() -> int:
    """Runs stage 2 (Haiku triage) against every fixture this manifest has enough
    ground truth to score, for both organizations, and reports recall, precision and
    accuracy against the recorded expectation — not just an agreement count. Needs
    ANTHROPIC_API_KEY. This is the check tests/calibration.py's own docstring points
    at for "a pass does not mean the model is calibrated" — here, on real pages
    instead of synthetic ones.
    """
    from agent.parse import to_candidate
    from agent.score import Budget, triage
    from agent.sources import Confidence, Source, Tier

    budget = Budget(ceiling_usd=0.60)
    tp = fp = tn = fn = 0
    disagreements: list[str] = []

    for org_name, program_slugs in _ORG_PROGRAM_GROUPS.items():
        cfg = _config_for(org_name, program_slugs)
        print(f"\n=== {org_name} ({'/'.join(program_slugs)}) ===\n")
        for fx in FIXTURES:
            expected = _expected_triage(fx, program_slugs)
            if expected is None:
                continue
            page, verdict = _load(fx)
            if verdict.rejected:
                # Stage 1 already rejected it (e.g. a real past deadline) — triage
                # never runs on this candidate in the real pipeline either, so there
                # is nothing for the live check to score here. Not a disagreement.
                print(f"  {fx.slug:<26} SKIPPED (stage 1 rejected: {verdict.reason.value})")
                continue
            source = Source(name=fx.funder, funder=fx.funder, url=fx.url,
                            tier=Tier.WARM, confidence=Confidence.CONFIRMED)
            candidate = to_candidate(page, fx.funder, int(Tier.WARM))
            try:
                relevant, reason = triage(candidate, budget, cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"  {fx.slug:<26} ERROR: {exc!r}")
                continue
            match = relevant == expected
            if relevant and expected:
                tp += 1
            elif relevant and not expected:
                fp += 1
            elif not relevant and not expected:
                tn += 1
            else:
                fn += 1
            mark = "✓" if match else "✗ DISAGREES"
            print(f"  {fx.slug:<26} expected={expected!s:<5} got={relevant!s:<5} {mark}")
            print(f"      model said: {reason}")
            if not match:
                disagreements.append(f"{org_name}/{fx.slug}: expected {expected}, "
                                     f"got {relevant} ({reason}) — {fx.reasoning}")

    total = tp + fp + tn + fn
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    accuracy = (tp + tn) / total if total else float("nan")
    false_positive_rate = fp / (fp + tn) if (fp + tn) else float("nan")

    print(f"\n{'=' * 70}")
    print(f"{total} scored (of {tp + fp + tn + fn} scored + skipped above). "
          f"TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"  recall (of real opportunities, how many did triage keep): "
          f"{recall:.1%}" if total else "  recall: n/a")
    print(f"  precision (of what triage kept, how many were real):      "
          f"{precision:.1%}" if total else "  precision: n/a")
    print(f"  accuracy (overall agreement with ground truth):           "
          f"{accuracy:.1%}" if total else "  accuracy: n/a")
    print(f"  false positive rate (of real negatives, how many leaked through): "
          f"{false_positive_rate:.1%}" if total else "  false positive rate: n/a")
    print(f"Cost: ${budget.spent_usd:.4f}")
    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s):")
        for d in disagreements:
            print(f"  - {d}")
    return 0


if __name__ == "__main__":
    if "--live" in sys.argv:
        raise SystemExit(_live_check())
    print(__doc__)
    print("Run `python3 -m pytest tests/test_golden_fixtures.py -v` for the offline "
         "checks, or `python3 -m tests.test_golden_fixtures --live` for the live one.")
