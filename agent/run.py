"""Entrypoint and orchestration. (CLAUDE.md §10)

The three tiers of §8, cheapest first:

    crawl()      fetch -> parse -> deterministic filters      free
    evaluate()   Haiku triage -> Sonnet scoring on the top N  metered by Budget

Every run ends on exactly one stop condition and says which: target_met, budget,
sources_exhausted, disabled, or error.

    python -m agent.run --no-llm              # free tiers only, $0.00
    python -m agent.run --sink jsonl          # needs ANTHROPIC_API_KEY to score
    python -m agent.run --sink sheets         # + RISE_SHEET_ID and a service account
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from .config import Config, ConfigUnavailable, load_config
from .fetch import Fetcher
from .filters import Flag, apply_filters
from .models import Opportunity, Program, RawCandidate, RunLog, StopReason, stable_id
from .parse import ParsedPage, parse_page, to_candidate
from .score import Budget, BudgetExceeded, score_one, triage
from .sources import Source, Tier, active_sources, unconfirmed_sources

log = logging.getLogger("rise")

def _is_thin_landing_page(page: ParsedPage) -> bool:
    """No amount, no deadline, barely any text — a nav page, not an opportunity.

    Dropping these is what keeps the Sheet readable in the one hour Mauri has (§9).
    """
    return (page.award_max is None
            and page.earliest_deadline is None
            and len(page.text) < 1200)


async def crawl(cfg: Config, run: RunLog,
                *, follow_links: bool = True) -> list[tuple[ParsedPage, Source]]:
    """Tier 1 of §8: fetch, parse, and apply the free deterministic filters.

    Returns only what survived. Every reject is counted in `run.rejected_by_filter`
    so the Runs tab shows what the free tier saved us from paying to think about.
    """
    sources = active_sources(cfg.max_tier)
    skipped = unconfirmed_sources(cfg.max_tier)

    for s in skipped:
        run.notes.append(f"SKIPPED (no confirmed URL): {s.name}")
        log.warning("Skipping %s — %s", s.name, s.notes or "no URL on file")

    survivors: dict[str, tuple[ParsedPage, Source]] = {}

    def consider(page: ParsedPage, source: Source) -> None:
        run.candidates_parsed += 1
        if page.url in survivors:
            return
        if _is_thin_landing_page(page):
            key = "thin_landing_page"
            run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + 1
            return
        verdict = apply_filters(page, source.funder, cfg)
        if verdict.rejected and verdict.reason:
            key = verdict.reason.value
            run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + 1
            log.debug("    rejected [%s] %s — %s", key, page.title[:50], verdict.detail)
            return
        if Flag.MATCH_REQUIREMENT in verdict.flags:
            run.notes.append(
                f"MATCH REQUIREMENT mentioned: {source.funder} — {page.title[:60]} "
                "(§11 Q4 unanswered, so not filtered)"
            )
        survivors[page.url] = (page, source)

    async with Fetcher() as fetcher:
        run.sources_attempted = len(sources)
        results = await fetcher.get_many([s.url for s in sources])  # type: ignore[misc]

        follow_up: list[tuple[Source, str]] = []

        for source, result in zip(sources, results):
            if not result.ok:
                run.sources_failed += 1
                run.notes.append(f"FETCH FAILED {source.funder}: {result.error or result.status}")
                log.warning("  ✗ %-46s %s", source.funder, result.error or result.status)
                continue

            run.sources_ok += 1
            page = parse_page(result.final_url or result.url, result.html or "")
            log.info(
                "  ✓ %-46s %d amounts, %d deadlines, %d links",
                source.funder, len(page.amounts), len(page.deadlines), len(page.links),
            )
            consider(page, source)

            if follow_links:
                follow_up.extend((source, url) for url in page.links[:6])

        # One level deep. Grant programs live on subpages; going deeper multiplies
        # requests against funders who did not ask to be crawled.
        if follow_up:
            log.info("Following %d program links…", len(follow_up))
            sub_results = await fetcher.get_many([u for _, u in follow_up])
            for (source, url), result in zip(follow_up, sub_results):
                if result.ok:
                    consider(parse_page(result.final_url or url, result.html or ""), source)

    return list(survivors.values())


def _rank_for_scoring(survivors: list[tuple[ParsedPage, Source]], cfg: Config) -> list:
    """Cheap ordering so the expensive tier sees the best candidates first.

    Not a score — just a spend-ordering heuristic, so that if the budget runs out
    we have already paid for the candidates most likely to be worth it.
    """
    def key(item):
        page, source = item
        return (
            1 if source.warm else 0,
            page.award_max or 0,
            1 if page.earliest_deadline else 0,
            len(page.text),
        )

    return sorted(survivors, key=key, reverse=True)


def _unscored(page: ParsedPage, source: Source, cfg: Config, note: str) -> Opportunity:
    """A survivor we never paid to score. Honest placeholder, never a fake score."""
    return Opportunity(
        id=stable_id(page.url, page.title),
        title=page.title[:300],
        funder=source.funder,
        award_min=page.award_min,
        award_max=page.award_max,
        deadline=page.earliest_deadline,
        estimated_effort_hours=None,
        program_match=[p for p in source.programs if p in cfg.programs_active]
                      or list(cfg.programs_active),
        score=0,
        score_rationale=note,
        source_url=page.url,
        verified=True,
        needs_human_check=True,
        fetched_at=datetime.now(timezone.utc),
    )


def evaluate(survivors: list[tuple[ParsedPage, Source]], cfg: Config, run: RunLog,
             budget: Budget, *, use_llm: bool) -> list[Opportunity]:
    """Tiers 2 and 3 of §8. Stops on the first stop condition to fire."""
    ranked = _rank_for_scoring(survivors, cfg)

    if not use_llm:
        run.stop_reason = StopReason.SOURCES_EXHAUSTED
        return [_unscored(p, s, cfg, "--no-llm: deterministic tiers only") for p, s in ranked]

    out: list[Opportunity] = []
    for page, source in ranked:
        if len(out) >= cfg.max_opportunities:
            run.stop_reason = StopReason.TARGET_MET
            log.info("Cap of %d reached — stopping.", cfg.max_opportunities)
            break

        candidate: RawCandidate = to_candidate(
            page, source.funder, int(source.tier),
            [p for p in source.programs if p in cfg.programs_active],
        )
        try:
            relevant, reason = triage(candidate, budget)          # tier 2 — Haiku
            if not relevant:
                key = "triage_not_an_opportunity"
                run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + 1
                continue
            out.append(score_one(candidate, source, cfg, budget))  # tier 3 — Sonnet
        except BudgetExceeded as exc:
            run.stop_reason = StopReason.BUDGET
            run.notes.append(f"BUDGET CEILING: {exc}")
            log.warning("Budget ceiling hit — %s", exc)
            break

    if run.stop_reason is None:
        run.stop_reason = StopReason.SOURCES_EXHAUSTED
    run.usd_spent = budget.spent_usd
    return out


def _report(cfg: Config, run: RunLog, opportunities: list[Opportunity]) -> None:
    from sinks.base import split_sections

    scored, not_stated = split_sections(opportunities)
    print("\n" + "=" * 78)
    print("RUN SUMMARY")
    print("=" * 78)
    print(f"  sources tried      {run.sources_attempted}")
    print(f"  fetched OK         {run.sources_ok}")
    print(f"  fetch failed       {run.sources_failed}")
    print(f"  pages parsed       {run.candidates_parsed}")
    print(f"  award amount found {len(scored)}")
    print(f"  amount not stated  {len(not_stated)}")
    print(f"  cost               ${run.usd_spent:.4f}")
    print(f"  stop reason        {run.stop_reason.value if run.stop_reason else '—'}")

    if run.rejected_by_filter:
        total = sum(run.rejected_by_filter.values())
        print(f"\n  rejected before any model call ({total} — free):")
        for reason, count in sorted(run.rejected_by_filter.items(),
                                    key=lambda kv: kv[1], reverse=True):
            print(f"    {count:>4}  {reason}")

    for warning in cfg.warnings:
        print(f"\n  ⚠ {warning}")
    if run.notes:
        print("\n  notes:")
        for note in run.notes:
            print(f"    · {note}")

    if scored:
        print("\n  RANKED — award amount stated")
        for o in scored[:15]:
            rng = (f"{o.award_min:,}–{o.award_max:,}"
                   if o.award_min != o.award_max else f"{o.award_max:,}")
            print(f"    {o.score:>3}  ${rng:>18}  {o.funder[:26]:<26}  {o.title[:36]}")
            if o.score_rationale:
                print(f"         {o.score_rationale[:96]}")
    if not_stated:
        print("\n  AMOUNT NOT STATED — needs a human look, not ranked")
        for o in not_stated[:15]:
            print(f"    {'—':>3}  {'—':>19}  {o.funder[:26]:<26}  {o.title[:36]}")
    print()


async def main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    run = RunLog(started_at=datetime.now(timezone.utc))
    try:
        cfg = load_config()
    except ConfigUnavailable as exc:
        # Strict mode: we could not confirm the kill switch is on, so we do not run.
        run.stop_reason = StopReason.ERROR
        run.finished_at = datetime.now(timezone.utc)
        run.notes.append(f"CONFIG UNAVAILABLE: {exc}")
        log.error("✗ %s", exc)
        return 1
    if args.max_tier:
        cfg.max_tier = Tier(args.max_tier)

    # Step 0: the kill switch. Before anything else, before any network call (§8).
    if not cfg.enabled:
        run.stop_reason = StopReason.DISABLED
        run.finished_at = datetime.now(timezone.utc)
        print("ENABLED is FALSE in the Config tab — exiting without doing anything.")
        return 0

    for warning in cfg.warnings:
        log.warning("⚠ %s", warning)

    use_llm = not args.no_llm
    if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "⚠ ANTHROPIC_API_KEY is not set — running deterministic tiers only. "
            "Nothing will be scored. Use --no-llm to make this explicit."
        )
        use_llm = False

    budget = Budget(ceiling_usd=args.budget or cfg.weekly_budget_usd)

    log.info("Crawling tier ≤ %d…", cfg.max_tier)
    try:
        survivors = await crawl(cfg, run, follow_links=not args.no_follow)
        log.info("%d candidates survived the free filters.", len(survivors))
        opportunities = evaluate(survivors, cfg, run, budget, use_llm=use_llm)
    except Exception as exc:  # noqa: BLE001
        run.stop_reason = StopReason.ERROR
        run.finished_at = datetime.now(timezone.utc)
        run.notes.append(f"ERROR: {exc!r}")
        log.exception("Run failed")
        return 1

    from sinks.base import split_sections

    scored, not_stated = split_sections(opportunities)
    run.opportunities_scored = len(scored)
    run.opportunities_not_stated = len(not_stated)
    run.finished_at = datetime.now(timezone.utc)

    _report(cfg, run, opportunities)

    if args.dry_run:
        print("--dry-run: nothing written.\n")
        return 0

    if args.sink == "sheets":
        from sinks.sheets import SheetsSink

        sink = SheetsSink()
        sink.ensure_config_tab()
    else:
        from sinks.jsonl import JsonlSink

        sink = JsonlSink(out_dir=args.out)

    written = sink.write_opportunities(opportunities)
    sink.write_run_log(run)
    print(f"Wrote {written} records via the {sink.name} sink.\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="RISE San Diego funding opportunity agent")
    p.add_argument("--sink", choices=["jsonl", "sheets"], default="jsonl")
    p.add_argument("--out", default="out", help="output dir for the jsonl sink")
    p.add_argument("--dry-run", action="store_true", help="crawl and report, write nothing")
    p.add_argument("--no-follow", action="store_true", help="do not follow program links")
    p.add_argument("--no-llm", action="store_true",
                   help="deterministic tiers only — no API calls, $0.00")
    p.add_argument("--budget", type=float,
                   help="override the weekly USD ceiling (default: 1.00, §8)")
    p.add_argument("--max-tier", type=int, choices=[1, 2, 3],
                   help="1=warm funders, 2=+intermediaries, 3=+government")
    p.add_argument("-v", "--verbose", action="store_true")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
