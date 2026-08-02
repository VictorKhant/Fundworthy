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
from datetime import date, datetime, timezone

from .apis import ADAPTERS, ApiResult
from .config import Config, ConfigUnavailable, load_config
from .fetch import Fetcher
from .filters import Flag, apply_filters
from .models import (
    Opportunity,
    Program,
    RawCandidate,
    RunLog,
    SourceHealth,
    SourceKind,
    SourceStatus,
    StopReason,
    stable_id,
)
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
        run.record(SourceHealth(
            name=s.name, funder=s.funder, status=SourceStatus.NOT_CHECKED,
            detail="no confirmed web address on file",
        ))
        log.warning("Skipping %s — %s", s.name, s.notes or "no URL on file")

    survivors: dict[str, tuple[ParsedPage, Source]] = {}
    match_flagged: list[str] = []

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
            # Counted, not narrated. The structured sources state matching funds on
            # every record, so one note each buries every other note in the Runs tab.
            match_flagged.append(page.title[:60])
        survivors[page.url] = (page, source)
        run.credit(source.funder)

    api_sources = [s for s in sources if s.is_api]
    html_sources = [s for s in sources if not s.is_api]
    run.sources_attempted = len(sources)

    async with Fetcher() as fetcher:
        # --- tier 0: the indexed APIs. Concurrent, bounded, no link-following. ---
        if api_sources:
            log.info("Querying %d indexed source(s)…", len(api_sources))
            api_results = await asyncio.gather(
                *(_run_adapter(s, fetcher, cfg) for s in api_sources)
            )
            for source, result in zip(api_sources, api_results):
                if result.error:
                    run.record(SourceHealth(
                        name=source.name, funder=source.funder,
                        status=SourceStatus.UNREACHABLE, detail=result.error,
                    ))
                    log.warning("  ✗ %-46s %s", source.funder, result.error)
                    continue
                run.record(SourceHealth(
                    name=source.name, funder=source.funder,
                    status=SourceStatus.OK, detail=result.note,
                ))
                log.info("  ✓ %-46s %s", source.funder, result.note)
                for key, count in result.rejected.items():
                    run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + count
                for page in result.pages:
                    consider(page, source)

        # --- tiers 1-3: the HTML crawl ---------------------------------------
        if not html_sources:
            run.finalize_health()
            return list(survivors.values())

        results = await fetcher.get_many([s.url for s in html_sources])  # type: ignore[misc]

        follow_up: list[tuple[Source, str]] = []

        for source, result in zip(html_sources, results):
            if not result.ok:
                run.record(SourceHealth(
                    name=source.name, funder=source.funder,
                    status=SourceStatus.UNREACHABLE,
                    detail=str(result.error or result.status),
                ))
                log.warning("  ✗ %-46s %s", source.funder, result.error or result.status)
                continue

            # A page that breaks the parser is one unhealthy source, not a dead run.
            try:
                page = parse_page(result.final_url or result.url, result.html or "")
            except Exception as exc:  # noqa: BLE001
                run.record(SourceHealth(
                    name=source.name, funder=source.funder,
                    status=SourceStatus.UNPARSEABLE, detail=f"{type(exc).__name__}: {exc}",
                ))
                log.warning("  ✗ %-46s could not be read: %r", source.funder, exc)
                continue

            run.record(SourceHealth(
                name=source.name, funder=source.funder, status=SourceStatus.OK,
            ))
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
                if not result.ok:
                    continue
                try:
                    consider(parse_page(result.final_url or url, result.html or ""), source)
                except Exception as exc:  # noqa: BLE001 — one bad subpage, not a dead run
                    log.debug("subpage %s could not be read: %r", url, exc)

    _note_match_requirements(run, match_flagged)
    run.finalize_health()
    return list(survivors.values())


def _note_match_requirements(run: RunLog, titles: list[str]) -> None:
    """One line about matching funds, not one per record.

    §11 Q4 (can RISE meet a match?) is unanswered, so these are surfaced rather than
    filtered — but surfacing has to stay readable to count as surfacing.
    """
    if not titles:
        return
    head = "; ".join(titles[:3])
    more = f" and {len(titles) - 3} more" if len(titles) > 3 else ""
    run.notes.append(
        f"MATCHING FUNDS mentioned on {len(titles)} opportunit(ies) — {head}{more}. "
        "Not filtered: §11 Q4 is unanswered."
    )


async def _run_adapter(source: Source, fetcher, cfg: Config) -> ApiResult:
    """Call one API adapter. Never raises — a broken API is one unhealthy source."""
    adapter = ADAPTERS.get(source.adapter or "")
    if adapter is None:
        return ApiResult(error=f"no adapter registered for {source.adapter!r}")
    try:
        return await adapter(fetcher, cfg)
    except Exception as exc:  # noqa: BLE001
        return ApiResult(error=f"{type(exc).__name__}: {exc}")


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
        source_kind=(SourceKind.INDEXED_DATABASE if source.is_api
                     else SourceKind.FUNDER_PAGE),
    )


def evaluate(survivors: list[tuple[ParsedPage, Source]], cfg: Config, run: RunLog,
             budget: Budget, *, use_llm: bool) -> list[Opportunity]:
    """Tiers 2 and 3 of §8. Stops on the first stop condition to fire."""
    ranked = _rank_for_scoring(survivors, cfg)
    per_kind = cfg.per_kind_cap
    kinds: dict[SourceKind, int] = {k: 0 for k in SourceKind}

    def kind_of(source: Source) -> SourceKind:
        return SourceKind.INDEXED_DATABASE if source.is_api else SourceKind.FUNDER_PAGE

    if not use_llm:
        run.stop_reason = StopReason.SOURCES_EXHAUSTED
        out = []
        for page, source in ranked:
            k = kind_of(source)
            if per_kind is not None and kinds[k] >= per_kind:
                continue
            kinds[k] += 1
            out.append(_unscored(page, source, cfg, "--no-llm: deterministic tiers only"))
        return out

    out: list[Opportunity] = []
    scoring_errors = 0
    for page, source in ranked:
        if per_kind is not None:
            # Balanced mode: each kind gets its own cap, and a candidate from a kind
            # that is already full is skipped *before* triage — paying Haiku to read
            # something we have already decided not to keep is pure waste.
            if all(n >= per_kind for n in kinds.values()):
                run.stop_reason = StopReason.TARGET_MET
                log.info("Per-source-kind cap of %d reached for both kinds.", per_kind)
                break
            if kinds[kind_of(source)] >= per_kind:
                continue
        elif len(out) >= cfg.max_opportunities:
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
            opp = score_one(candidate, source, cfg, budget)        # tier 3 — Sonnet
            # Post-scoring deadline guard: §7 rejects passed deadlines, but the
            # deterministic parser (tier 1) often can't find the date. Sonnet does.
            # Enforce the hard reject here, now that we have a trustworthy deadline.
            if opp.deadline is not None and opp.deadline < date.today():
                key = "deadline_passed"
                run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + 1
                log.info("  dropped (deadline %s passed): %s", opp.deadline, opp.title[:40])
                continue
            kinds[opp.source_kind] += 1
            out.append(opp)
        except BudgetExceeded as exc:
            run.stop_reason = StopReason.BUDGET
            run.notes.append(f"BUDGET CEILING: {exc}")
            log.warning("Budget ceiling hit — %s", exc)
            break
        except Exception as exc:  # noqa: BLE001
            # One candidate failing to score must not discard the ones already
            # scored, or the ones after it. The budget ceiling is the only thing
            # that stops this loop.
            scoring_errors += 1
            log.warning("  ! could not score %s — %r", page.title[:40], exc)
            if scoring_errors == 1:
                run.notes.append(f"SCORING ERROR ({source.funder}): {exc!r}")
            continue

    if scoring_errors:
        run.notes.append(f"{scoring_errors} opportunit(ies) could not be scored this run")

    if per_kind is not None:
        # Say so when a kind came up short. A balanced request that quietly returns
        # fewer reads as "that is all there was", when the real cause is that the
        # candidates existed and were rejected downstream.
        short = {k.label: n for k, n in kinds.items() if n < per_kind}
        if short:
            run.notes.append(
                "BALANCE NOT MET (asked for "
                + f"{per_kind} of each): "
                + ", ".join(f"{label} returned {n}" for label, n in short.items())
                + " — the shortfall was rejected by triage or by the deadline guard, "
                "not padded with weaker results."
            )

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

    if run.source_health:
        print("\n  SOURCE HEALTH")
        marks = {"unreachable": "✗", "unparseable": "✗",
                 "not_checked": "?", "no_results": "·", "ok": "✓"}
        for h in sorted(run.source_health, key=lambda x: (not x.degraded, x.funder)):
            mark = marks.get(h.status.value, "·")
            line = f"    {mark} {h.funder[:34]:<34} {h.status.value:<13}"
            if h.candidates:
                line += f" {h.candidates:>3} kept"
            print(line)
            if h.detail:
                print(f"        {h.detail[:88]}")

    for warning in cfg.warnings:
        print(f"\n  ⚠ {warning}")
    if run.notes:
        print("\n  notes:")
        for note in run.notes:
            print(f"    · {note}")

    if scored:
        print("\n  RANKED — award amount stated")
        for o in scored[:15]:
            lo, hi = o.award_min, o.award_max
            if lo is not None and hi is not None:
                rng = f"{lo:,}–{hi:,}" if lo != hi else f"{hi:,}"
            elif hi is not None:
                rng = f"{hi:,}"
            elif lo is not None:
                rng = f"{lo:,}"
            else:
                rng = "—"
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
    if args.balance:
        cfg.per_kind_cap = args.balance

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
    opportunities: list[Opportunity] = []
    failed = False
    try:
        survivors = await crawl(cfg, run, follow_links=not args.no_follow)
        log.info("%d candidates survived the free filters.", len(survivors))
        opportunities = evaluate(survivors, cfg, run, budget, use_llm=use_llm)
    except Exception as exc:  # noqa: BLE001
        # Whatever went wrong, Mauri still gets what we did find, plus a run log
        # saying it was incomplete. A silent empty Sheet on Thursday morning is
        # worse than a short one with an explanation on it.
        failed = True
        run.stop_reason = StopReason.PARTIAL if opportunities else StopReason.ERROR
        run.notes.append(f"ERROR: {exc!r}")
        log.exception("Run failed — writing whatever was collected before the failure")

    from sinks.base import split_sections

    scored, not_stated = split_sections(opportunities)
    run.opportunities_scored = len(scored)
    run.opportunities_not_stated = len(not_stated)
    run.finished_at = datetime.now(timezone.utc)

    _report(cfg, run, opportunities)

    if args.dry_run:
        print("--dry-run: nothing written.\n")
        return 1 if failed else 0

    try:
        if args.sink == "sheets":
            from sinks.sheets import SheetsSink

            sink = SheetsSink()
            sink.ensure_config_tab()
        else:
            from sinks.jsonl import JsonlSink

            sink = JsonlSink(out_dir=args.out)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not open the %s sink: %r", args.sink, exc)
        return 1

    written = 0
    try:
        written = sink.write_opportunities(opportunities, run)
    except Exception as exc:  # noqa: BLE001
        # Still write the run log below: a Runs row saying the write failed is how
        # Mauri finds out, without calling anyone (§13).
        failed = True
        run.stop_reason = StopReason.PARTIAL
        run.notes.append(f"WRITE FAILED: {exc!r}")
        log.exception("Writing opportunities failed")

    try:
        sink.write_run_log(run)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not write the run log: %r", exc)

    print(f"Wrote {written} records via the {sink.name} sink.\n")
    return 1 if failed else 0


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
    p.add_argument("--balance", type=int, metavar="N",
                   help="take up to N from funder pages AND N from indexed databases, "
                        "instead of one combined cap")
    p.add_argument("-v", "--verbose", action="store_true")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
