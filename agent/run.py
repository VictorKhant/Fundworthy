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


def resolve_sources(cfg: Config, run: RunLog) -> tuple[list[Source], list[Source]]:
    """Which funder pages this run visits.

    The funders table wins when it exists — that is the list Mauri edits. The shipped
    registry in sources.py is the fallback for a fresh clone with no database. Either
    way, sources she has deactivated never get fetched, and a partner who stopped
    funding RISE stops costing us requests without losing its record.
    """
    from .sources import sources_from_db

    from_db = sources_from_db(cfg.max_tier, cfg.sectors_active)
    if from_db is not None:
        sources, skipped = from_db
        run.notes.append(
            f"Sources: {len(sources)} from the funders list "
            f"(sectors: {', '.join(cfg.sectors_active) or 'all'})"
        )
        return sources, skipped

    run.notes.append("Sources: shipped registry (no funders database found)")
    return active_sources(cfg.max_tier), unconfirmed_sources(cfg.max_tier)


def _discover_extra(cfg: Config, run: RunLog) -> list[Source]:
    """Sources from beyond the partner list, when Mauri asked for them.

    The provider itself lives on another branch (agent/discovery.py explains why). What
    matters here is that the run log distinguishes "we looked and found nothing" from
    "nothing looked" — those are very different weeks and they must not read the same.
    """
    if not cfg.search_beyond_partners:
        return []

    from .discovery import get_provider

    provider = get_provider()
    found = provider.discover(cfg.programs, sectors=cfg.sectors_active, limit=25)
    run.notes.append(
        f"Beyond-partners search: provider={provider.name}, {len(found)} source(s)."
        + ("  NOTE: no discovery provider is installed, so this ran over the partner "
           "list only." if provider.name == "none" else "")
    )
    return found


async def crawl(cfg: Config, run: RunLog,
                *, follow_links: bool = True,
                already_seen: set[str] | None = None) -> list[tuple[ParsedPage, Source]]:
    """Tier 1 of §8: fetch, parse, and apply the free deterministic filters.

    Returns only what survived. Every reject is counted in `run.rejected_by_filter`
    so the Runs tab shows what the free tier saved us from paying to think about.
    """
    sources, skipped = resolve_sources(cfg, run)
    sources = sources + _discover_extra(cfg, run)
    already_seen = already_seen or set()

    for s in skipped:
        run.notes.append(f"SKIPPED (no confirmed URL): {s.name}")
        log.warning("Skipping %s — %s", s.name, s.notes or "no URL on file")

    survivors: dict[str, tuple[ParsedPage, Source]] = {}

    def consider(page: ParsedPage, source: Source) -> None:
        run.candidates_parsed += 1
        if page.url in survivors:
            return

        # Already shown to Mauri this month. Dropping it here — in the free tier,
        # before triage — is the point: a repeat finding costs $0.00 rather than a
        # Haiku call, and she does not re-read the same row four Thursdays running.
        # The archive resets monthly, so it can legitimately come back later.
        if stable_id(page.url, page.title) in already_seen:
            key = "already_seen_this_month"
            run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + 1
            run.duplicates_skipped += 1
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
            relevant, reason = triage(candidate, budget, cfg)     # tier 2 — Haiku
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
            out.append(opp)
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

    # Create and seed the settings database before reading config, so a first run picks
    # up the defaults from the same place every later run reads them.
    #
    # Deliberately NOT done under RISE_STRICT_CONFIG. Strict mode is the scheduled job,
    # where the database is not checked in — auto-creating it there would hand back a
    # fresh `enabled=1` on every run and silently defeat the kill switch, which is the
    # exact failure evidence/README.md E7 was written about. In strict mode a config we
    # cannot read stays a refusal to run.
    strict = os.environ.get("RISE_STRICT_CONFIG", "").strip().lower() in {
        "1", "true", "yes", "on"}
    if not strict and not args.no_archive:
        try:
            from app.db import init_db

            init_db()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open the settings database (%s).", exc)

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
    if args.max_opportunities:
        cfg.max_opportunities = args.max_opportunities

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

    # The monthly archive, both halves. The purge bounds the file; `already_seen` is
    # what keeps Mauri from re-reading the same grant every Thursday. Both are skipped
    # silently if there is no database — the agent still has to run from a fresh clone.
    already_seen: set[str] = set()
    if not args.no_archive:
        try:
            from app.archive import purge_old_months, seen_ids_this_month
            from app.db import init_db, session

            init_db()
            with session() as conn:
                run.purged_rows = purge_old_months(conn)
                already_seen = seen_ids_this_month(conn)
            if run.purged_rows:
                run.notes.append(
                    f"Archive: purged {run.purged_rows} row(s) from earlier months.")
            log.info("Archive: %d finding(s) already shown this month.", len(already_seen))
        except Exception as exc:  # noqa: BLE001
            log.warning("Archive unavailable (%s) — running without dedup.", exc)
            run.notes.append(f"Archive unavailable: {exc}")

    log.info("Crawling tier ≤ %d…", cfg.max_tier)
    try:
        survivors = await crawl(cfg, run, follow_links=not args.no_follow,
                                already_seen=already_seen)
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

    sinks = []
    if args.sink == "sheets":
        from sinks.sheets import SheetsSink

        sheets = SheetsSink()
        sheets.ensure_config_tab()
        sinks.append(sheets)
    elif args.sink == "jsonl":
        from sinks.jsonl import JsonlSink

        sinks.append(JsonlSink(out_dir=args.out))
    else:
        # The default is both: SQLite is what the dashboard reads and what next week's
        # dedup checks against, and run.json keeps the static export path alive for
        # the GitHub Actions run and for anyone opening the built site directly.
        from sinks.sqlite import SqliteSink
        from sinks.webjson import WebJsonSink

        sinks.append(SqliteSink(run_id=args.run_id))
        sinks.append(WebJsonSink(out_path=args.web_out))

    written = 0
    for sink in sinks:
        written = sink.write_opportunities(opportunities)
        sink.write_run_log(run)
    print(f"Wrote {written} records via: {', '.join(s.name for s in sinks)}.\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="RISE San Diego funding opportunity agent")
    p.add_argument("--sink", choices=["db", "web", "jsonl", "sheets"], default="db",
                   help="db (default) writes SQLite + run.json; sheets is now export-only")
    p.add_argument("--run-id", help="attach this run's findings to an existing run row")
    p.add_argument("--no-archive", action="store_true",
                   help="skip the monthly dedup and purge (shows repeats again)")
    p.add_argument("--out", default="out", help="output dir for the jsonl sink")
    p.add_argument("--web-out", default="dashboard/public/run.json",
                   help="output path for the web sink (the file the dashboard reads)")
    p.add_argument("--dry-run", action="store_true", help="crawl and report, write nothing")
    p.add_argument("--no-follow", action="store_true", help="do not follow program links")
    p.add_argument("--no-llm", action="store_true",
                   help="deterministic tiers only — no API calls, $0.00")
    p.add_argument("--budget", type=float,
                   help="override the weekly USD ceiling (default: 1.00, §8)")
    p.add_argument("--max-tier", type=int, choices=[1, 2, 3],
                   help="1=warm funders, 2=+intermediaries, 3=+government")
    p.add_argument("--max-opportunities", type=int,
                   help="cap how many to score this run (overrides Config — handy for a fast test)")
    p.add_argument("-v", "--verbose", action="store_true")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
