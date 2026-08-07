"""What the three stage boxes claim a run did, and whether the run agrees.

Offline: `triage` and `score_one` are monkeypatched, so no key and no network. The two
bugs these were written against both had the same shape — the pipeline knew something and
the panel built to explain it showed something else:

  1  Stage 1's "set aside" figure is `candidates_parsed - triaged`, while the breakdown
     beneath it comes from `rejected_by_filter`. Rejects made *inside* an API adapter went
     into the second and not the first, so a run showed "47 set aside" above a list whose
     first two rows already summed past 118. Both numbers were right about different
     populations.

  2  A triage call that raised was counted in `scoring_errors`, logged, and written once
     into `run.notes` — none of which any dashboard component rendered. So a search whose
     every model call failed showed "164 came in, 0 went through, $0.0000 spent" above the
     words "Nothing was set aside at this step".
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import run as runmod  # noqa: E402
from agent.config import Config, ProgramCard  # noqa: E402
from agent.models import RunLog, StopReason  # noqa: E402
from agent.parse import ParsedPage  # noqa: E402
from agent.score import Budget  # noqa: E402
from agent.sources import Confidence, Source, Tier  # noqa: E402


def _cfg(**kw) -> Config:
    cfg = Config(programs=[ProgramCard(slug="housing", name="Housing",
                                       summary="Supportive housing")])
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _run() -> RunLog:
    return RunLog(started_at=datetime.now(timezone.utc))


def _page(url: str, *, amount: int | None = 50_000) -> ParsedPage:
    page = ParsedPage(url=url, title="A grant", text="x" * 3000)
    if amount is not None:
        page.amounts = [type("E", (), {"value": amount, "snippet": "$", "kind": "amount"})()]
    return page


def _src(name: str) -> Source:
    return Source(name=name, funder=name, url=f"https://{name}.invalid",
                  tier=Tier.WARM, confidence=Confidence.CONFIRMED)


def _survivors(n: int) -> list[tuple[ParsedPage, Source]]:
    return [(_page(f"https://f{i}.invalid"), _src(f"funder{i}")) for i in range(n)]


# --- bug 1: the two halves of stage 1 must count the same population -----------

def test_the_real_pipeline_counts_adapter_rejects_in_the_parsed_total(monkeypatch):
    """The CA Grants Portal filters records before they ever reach `consider()`, so its
    rejects landed in `rejected_by_filter` while `candidates_parsed` never moved. Stage 1
    then showed a "set aside" total smaller than the breakdown printed underneath it.

    A record the adapter refused *was* a candidate we considered and declined, for free,
    exactly like a page that fails `apply_filters` — so it belongs in both counters.

    Driven through `crawl()` itself rather than a transcription of the counter, because a
    test that re-implements the fix in its own body passes whatever production does."""
    import asyncio

    from agent.apis import ApiResult

    run = _run()
    cfg = _cfg()

    api_source = Source(name="CA", funder="State of California",
                        url="https://ca.invalid", tier=Tier.INDEXED,
                        confidence=Confidence.CONFIRMED, adapter="ca_grants_portal")

    monkeypatch.setattr(runmod, "resolve_sources", lambda c, r: ([api_source], []))
    monkeypatch.setattr(runmod, "excluded_funders", lambda org_id: set())

    async def fake_adapter(source, fetcher, cfg):
        result = ApiResult(note="stubbed")
        for _ in range(7):
            result.reject("ca_category_off_mission")
        return result

    monkeypatch.setattr(runmod, "_run_adapter", fake_adapter)

    asyncio.run(runmod.crawl(cfg, run, follow_links=False))

    assert run.rejected_by_filter["ca_category_off_mission"] == 7
    assert run.candidates_parsed == 7, (
        "the adapter turned away 7 records and stage 1 would report 0 came in — the "
        "breakdown and the total would disagree on screen"
    )


# --- bug 2: a failing tier must say so where every other reason appears --------

def test_a_failing_triage_is_recorded_against_stage_2_with_the_real_error(monkeypatch):
    """The bug in one assertion: these rows did not exist, so the panel said "nothing was
    set aside" about 164 consecutive failures."""
    run, cfg = _run(), _cfg()

    def boom(candidate, budget, cfg):
        raise RuntimeError("authentication_error: invalid x-api-key")

    monkeypatch.setattr(runmod, "triage", boom)

    runmod.evaluate(_survivors(3), cfg, run, Budget(ceiling_usd=1.0), use_llm=True)

    stage2 = [r for r in run.rejects if r.stage == 2]
    assert stage2, "a failing triage recorded nothing at all"
    assert all(r.reason == "triage_error" for r in stage2)
    # The actual exception, in the same slot that holds "$4,000 < $10,000".
    assert "invalid x-api-key" in stage2[0].detail
    assert run.rejected_by_filter["triage_error"] == len(stage2)


def test_a_failing_scorer_is_recorded_against_stage_3_not_stage_2(monkeypatch):
    """Triage worked, scoring did not. Recorded against the box that was actually
    running, or the panel sends somebody to look at the wrong step."""
    run, cfg = _run(), _cfg()

    monkeypatch.setattr(runmod, "triage", lambda c, b, cf: (True, "looks like a grant"))

    def boom(candidate, source, cfg, budget):
        raise RuntimeError("overloaded_error: server busy")

    monkeypatch.setattr(runmod, "score_one", boom)

    runmod.evaluate(_survivors(3), cfg, run, Budget(ceiling_usd=1.0), use_llm=True)

    assert [r.reason for r in run.rejects if r.stage == 3], "nothing recorded at tier 3"
    assert not [r for r in run.rejects if r.reason == "triage_error"], \
        "triage succeeded — its box must not be blamed for the scorer's failure"
    assert "server busy" in [r for r in run.rejects if r.stage == 3][0].detail


def test_a_systemic_failure_stops_the_run_instead_of_walking_the_whole_list(monkeypatch):
    """The circuit breaker. An expired key fails identically on every candidate, and the
    loop used to work through all of them one API error at a time — spending minutes to
    learn what the fifth attempt already knew, and ending in something that looks from
    the outside exactly like a quiet week."""
    run, cfg = _run(), _cfg()
    calls = {"n": 0}

    def boom(candidate, budget, cfg):
        calls["n"] += 1
        raise RuntimeError("authentication_error: invalid x-api-key")

    monkeypatch.setattr(runmod, "triage", boom)

    runmod.evaluate(_survivors(80), cfg, run, Budget(ceiling_usd=1.0), use_llm=True)

    assert calls["n"] == runmod.CONSECUTIVE_ERROR_LIMIT, (
        f"tried {calls['n']} candidates; the breaker should have stopped it at "
        f"{runmod.CONSECUTIVE_ERROR_LIMIT}"
    )
    assert run.stop_reason is StopReason.ERROR, \
        "a broken run must not end as `sources_exhausted`, which reads as a quiet week"
    assert any("not a quiet week" in n for n in run.notes)


def test_one_bad_page_among_good_ones_does_not_stop_the_run(monkeypatch):
    """The other half of the breaker, and the reason it counts *consecutive* failures.
    A single unreadable page is ordinary and must never abort a search."""
    run, cfg = _run(), _cfg()
    seen = {"n": 0}

    def sometimes(candidate, budget, cfg):
        seen["n"] += 1
        if seen["n"] == 2:
            raise RuntimeError("ValueError: one odd page")
        return False, "not an open call"

    monkeypatch.setattr(runmod, "triage", sometimes)

    runmod.evaluate(_survivors(12), cfg, run, Budget(ceiling_usd=1.0), use_llm=True)

    assert seen["n"] == 12, "one failure in the middle stopped the whole run"
    assert run.stop_reason is StopReason.SOURCES_EXHAUSTED
    assert run.rejected_by_filter.get("triage_error") == 1


def test_a_scoring_failure_leaves_a_note_a_person_can_read(monkeypatch):
    """`run.notes` is the only place the run speaks in sentences, and the dashboard now
    renders it. The note has to name the funder and carry the real error."""
    run, cfg = _run(), _cfg()

    def boom(candidate, budget, cfg):
        raise RuntimeError("authentication_error: invalid x-api-key")

    monkeypatch.setattr(runmod, "triage", boom)

    runmod.evaluate(_survivors(2), cfg, run, Budget(ceiling_usd=1.0), use_llm=True)

    joined = " ".join(run.notes)
    assert "funder0" in joined
    assert "invalid x-api-key" in joined
