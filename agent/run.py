"""Entrypoint and orchestration. (CLAUDE.md)

The three tiers of §8, cheapest first:

    crawl()      fetch -> parse -> deterministic filters      free
    evaluate()   Haiku triage -> Sonnet scoring on the top N  metered by Budget

Every run ends on exactly one stop condition and says which: target_met, budget,
sources_exhausted, disabled, or error.

    python -m agent.run --no-llm              # free tiers only, $0.00
    python -m agent.run --sink jsonl          # needs ANTHROPIC_API_KEY to score
    python -m agent.run --sink sheets         # + FUNDWORTHY_SHEET_ID and a service account
"""

from __future__ import annotations

import argparse
import signal
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone

from .apis import ADAPTERS, ApiResult
from .config import Config, ConfigUnavailable, load_config
from .fetch import Fetcher
from .filters import Flag, apply_filters
from .models import (
    MAX_REJECTS,
    Opportunity,
    Program,
    RawCandidate,
    Reject,
    RunLog,
    SourceHealth,
    SourceKind,
    SourceStatus,
    StopReason,
    stable_id,
)
from .parse import ParsedPage, parse_page, to_candidate
from .score import STAGE_MARKER, Budget, BudgetExceeded, score_one, triage
from .sources import Source, Tier, active_sources, unconfirmed_sources

log = logging.getLogger("rise")

# How many candidates in a row may fail before the run gives up on the whole list. Five
# rather than one, because a single unreadable page is ordinary and must not abort a
# search; five identical failures in a row is a broken key, a bad model id or an outage,
# and every further attempt spends time to learn nothing new. See the circuit breaker in
# `evaluate`.
CONSECUTIVE_ERROR_LIMIT = 5


def _emit_funnel(run: RunLog, *, survivors: int | None = None,
                 kept: int | None = None) -> None:
    """Print the funnel as it stands, for the three stage boxes on This week.

    The boxes used to be hidden for the whole of a run and appear at the end holding the
    finished numbers, which made the one thing somebody watches for five to ten minutes —
    *is this working?* — the one thing they could not see. Now they are the run.

    Same shape as the spend marker beside it: a line on stdout that `app/runner.py: _pump`
    consumes and drops. The child must not write the run row itself — the sink owns it,
    and a mid-run write from here would race the process that is about to finish it.

    `survivors` and `kept` are the two denominators. `parsed`/`triaged`/`scored` count
    what has been *done*, and a count with nothing to divide by cannot fill a bar: stage 2
    is "of the pages that survived the free filters, how many have been read", and stage 3
    is "of the results you asked for, how many are found". Both are real stop conditions
    (`sources_exhausted`, `target_met`) rather than a fraction invented to make a bar move.
    """
    funnel = {
        "parsed": run.candidates_parsed,
        "triaged": run.triaged,
        "scored": run.scored,
    }
    if survivors is not None:
        funnel["survivors"] = survivors
    if kept is not None:
        funnel["kept"] = kept
    log.info("%s%s", STAGE_MARKER, json.dumps(funnel, separators=(",", ":")))


def _is_thin_landing_page(page: ParsedPage) -> bool:
    """No amount, no deadline, barely any text — a nav page, not an opportunity.

    Dropping these is what keeps the Sheet readable in the one hour the user has (§9).
    """
    return (page.award_max is None
            and page.earliest_deadline is None
            and len(page.text) < 1200)


def resolve_sources(cfg: Config, run: RunLog) -> tuple[list[Source], list[Source]]:
    """Which funder pages this run visits.

    The funders table wins when it exists — that is the list the user edits. The shipped
    registry in sources.py is the fallback for a fresh clone with no database. Either
    way, sources they have deactivated never get fetched, and a partner who stopped
    funding the organization stops costing us requests without losing its record.
    """
    from .sources import sources_from_db

    from_db = sources_from_db(cfg.max_tier, cfg.sectors_active,
                              org_id=cfg.org_id)
    if from_db is not None:
        sources, skipped = from_db
        run.notes.append(
            f"Sources: {len(sources)} from the funders list "
            f"(sectors: {', '.join(cfg.sectors_active) or 'all'})"
        )
        return sources, skipped

    # `sources_from_db` returns None for two very different reasons: no database file
    # yet (a fresh clone — expected), or the database exists but the read itself
    # failed (already logged there). Telling them apart here, once, is what stops the
    # run notes from claiming "no funders database found" when the real cause was a
    # transient read error against an org's actual funder list. Wrapped the same way
    # `excluded_funders` above treats app.db as optional — an agent/-only checkout
    # with no app package must still get the (more conservative) default message.
    db_exists = False
    try:
        from app.db import db_path as _db_path
        db_exists = _db_path().exists()
    except Exception:  # noqa: BLE001
        pass

    if db_exists:
        run.notes.append(
            "Sources: shipped registry (could not read the funders list — see the "
            "technical log)"
        )
    else:
        run.notes.append("Sources: shipped registry (no funders database found)")
    return active_sources(cfg.max_tier), unconfirmed_sources(cfg.max_tier)


def _discover_extra(cfg: Config, run: RunLog) -> list[Source]:
    """Sources from beyond the partner list, when the user asked for them.

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


def excluded_funders(org_id: str) -> set[str]:
    """The remove list — funders the user has taken out of the search, casefolded.

    Sources on it are never fetched (they are `active=0`, so `sources_from_db` does not
    return them at all). This set closes the other door: the two indexed databases
    return grants from every funder in the state, so an excluded funder can still reach
    them through Grants.gov or the CA portal unless we drop it on the way in.
    """
    try:
        from app.db import db_path, session
        from app.repo import excluded_funder_names

        if not db_path().exists():
            return set()
        with session() as conn:
            return excluded_funder_names(conn, org_id=org_id)
    except Exception:  # noqa: BLE001 — no database is a normal state
        return set()


def _on_remove_list(funder: str, title: str, excluded: set[str]) -> bool:
    """Is this candidate excluded, by funder or by named programme?

    An exact funder match removes the whole organisation. A remove-list entry that
    appears inside the page title removes just that programme — which is the case §7
    always described and never actually implemented.

    Substring matching is deliberately one-directional: the entry must appear in the
    title, not the reverse. "County of San Diego" would otherwise match every County
    page, which is exactly the over-reach §7 warned against.
    """
    if funder.strip().casefold() in excluded:
        return True
    haystack = f"{funder} {title}".casefold()
    return any(len(name) > 12 and name in haystack for name in excluded)


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
    excluded = excluded_funders(cfg.org_id)
    if excluded:
        run.notes.append(
            f"Remove list: {len(excluded)} funder(s) excluded from this search — "
            "not fetched, not read, not scored."
        )

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
        # `survivors` and not `triaged` is what stage 1's number means: "pages worth
        # paying to read". Triage has not started yet during the crawl, so reporting the
        # triaged count here would show a zero on the box that is currently working.
        _emit_funnel(run, survivors=len(survivors))
        if page.url in survivors:
            return

        # The remove list, second door. A source on it is never fetched — but the
        # indexed databases carry grants from every funder in the state, so one can
        # still arrive that way. Dropped here, before triage, so it costs nothing.
        #
        # Matched against the page TITLE as well as the funder, so a single named
        # programme can be removed without removing its funder. That is what §7 asked
        # for and never got: "the Equity Impact Grant is a hard reject — that is one
        # program, not the whole County. Other County solicitations stay eligible."
        if _on_remove_list(source.funder, page.title, excluded):
            run.reject(1, "on_the_remove_list", funder=source.funder,
                       title=page.title, url=page.url,
                       detail="you took this one off the search")
            return

        # Already shown to the user this month. Dropping it here — in the free tier,
        # before triage — is the point: a repeat finding costs $0.00 rather than a
        # Haiku call, and they do not re-read the same row four Thursdays running.
        # The archive resets monthly, so it can legitimately come back later.
        if stable_id(page.url, page.title) in already_seen:
            run.reject(1, "already_seen_this_month", funder=source.funder,
                       title=page.title, url=page.url,
                       detail="already on this month's list")
            run.duplicates_skipped += 1
            return

        if _is_thin_landing_page(page):
            run.reject(1, "thin_landing_page", funder=source.funder,
                       title=page.title, url=page.url,
                       detail=f"{len(page.text)} characters, no amount and no deadline")
            return
        verdict = apply_filters(page, source.funder, cfg)
        if verdict.rejected and verdict.reason:
            # `verdict.detail` is the specific fact — "$4,000 < $10,000", the parsed
            # deadline, the matched remove-list fragment. It was logged at DEBUG and
            # dropped; it is the one thing that makes a reject checkable by the person
            # whose funder list produced it.
            run.reject(1, verdict.reason.value, funder=source.funder,
                       title=page.title, url=page.url, detail=verdict.detail)
            log.debug("    rejected [%s] %s — %s",
                      verdict.reason.value, page.title[:50], verdict.detail)
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
                # Warnings are things the user can act on — a ticked program whose card is
                # empty searched nothing. They go in the run notes, where they read
                # them, not only in this source's detail line.
                for warning in result.warnings:
                    run.notes.append(warning)
                    log.warning("  ⚠ %s", warning)
                # Already aggregated by the adapter, so these are counts without rows.
                # The stage boxes show them in the totals and say the detail is not
                # available rather than inventing one.
                #
                # `candidates_parsed` counts them too, and it did not, which made stage 1
                # contradict itself on screen. The box reads "came in" from
                # `candidates_parsed` and "set aside" from came-minus-through, while the
                # breakdown underneath comes from `rejected_by_filter` — so a run where
                # the CA portal turned away 118 records off-mission showed "47 set aside"
                # above a list whose first two rows already summed past 118. Both numbers
                # were right about different populations, which is the one way a panel
                # built to explain a thin week can make it less explicable. A record the
                # adapter refused *was* a candidate we considered and declined, for free,
                # exactly like a page that fails `apply_filters`.
                for key, count in result.rejected.items():
                    run.rejected_by_filter[key] = run.rejected_by_filter.get(key, 0) + count
                    run.candidates_parsed += count
                for page in result.pages:
                    consider(page, source)

        # --- tiers 1-3: the HTML crawl ---------------------------------------
        if not html_sources:
            run.survivors = len(survivors)
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
    # Stage 1's number, recorded before anything reads a page. Set on both return paths
    # deliberately: the early one (no HTML sources, only indexed databases) is a real run
    # and its box has to be right too.
    run.survivors = len(survivors)
    run.finalize_health()
    return list(survivors.values())


def _note_match_requirements(run: RunLog, titles: list[str]) -> None:
    """One line about matching funds, not one per record.

    §11 Q4 (can the organization meet a match?) is unanswered, so these are surfaced rather than
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
        # `1 if source.warm else 0` used to lead this tuple, so the organization's existing
        # relationships always spent the scoring budget first. The stakeholder has since
        # said they already receive money from those funders and do not want to reapply,
        # so warmth is no longer a priority signal anywhere — a warm funder they want
        # skipped goes on the remove list and is never fetched at all.
        return (
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
        # Matched nothing and matched everything must not be stored identically. This was
        # `[...] or list(cfg.programs_active)`, so a page the funder registry claims no
        # program for was recorded as matching all of them — and the row then renders
        # "For: every program you run" on something nobody has read. `score_one` was fixed
        # for exactly this (see the note there); the placeholder path kept the bug, which
        # is worse here, because these are the rows we never paid to look at.
        program_match=[p for p in source.programs if p in cfg.programs_active],
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
    # Consecutive, not total: a handful of odd pages across a long list is ordinary, and
    # the same failure on every page in a row is not. Only the second one is worth
    # abandoning a run over. Reset by any candidate that completes its intended path,
    # including one triage rejects — a working model call proves the pipeline is alive.
    consecutive_errors = 0
    # The two denominators the boxes divide by, sent once before the loop so stage 2's
    # bar has a total to fill against from its first tick rather than after its first
    # candidate.
    _emit_funnel(run, survivors=len(ranked), kept=0)
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
        # Which tier is working, so a failure is recorded against the box that was
        # actually running when it happened rather than always against scoring.
        phase = 2
        try:
            run.triaged += 1
            _emit_funnel(run, survivors=len(ranked), kept=len(out))
            relevant, reason = triage(candidate, budget, cfg)     # tier 2 — Haiku
            if not relevant:
                # `reason` is the model's own ≤15-word answer. It used to be formatted
                # into a log line and dropped, which meant the one tier that can explain
                # itself in English was the one tier that explained nothing.
                run.reject(2, "triage_not_an_opportunity", funder=source.funder,
                           title=candidate.title, url=candidate.source_url,
                           detail=reason)
                consecutive_errors = 0
                continue
            run.scored += 1
            phase = 3
            _emit_funnel(run, survivors=len(ranked), kept=len(out))
            opp = score_one(candidate, source, cfg, budget)        # tier 3 — Sonnet
            # Post-scoring deadline guard: §7 rejects passed deadlines, but the
            # deterministic parser (tier 1) often can't find the date. Sonnet does.
            # Enforce the hard reject here, now that we have a trustworthy deadline.
            if opp.deadline is not None and opp.deadline < date.today():
                run.reject(3, "deadline_passed", funder=source.funder,
                           title=opp.title, url=opp.source_url,
                           detail=f"closed {opp.deadline.isoformat()}")
                log.info("  dropped (deadline %s passed): %s", opp.deadline, opp.title[:40])
                consecutive_errors = 0
                continue

            # Not a reject — it is kept and shown — but the accuracy gate stripping a
            # value is the single most useful thing tier 3 can tell somebody about its
            # own reliability, and it was only ever a log warning.
            if opp.needs_human_check and len(run.rejects) < MAX_REJECTS:
                run.rejects.append(Reject(
                    stage=3, reason="claim_could_not_be_confirmed",
                    funder=source.funder, title=opp.title, url=opp.source_url,
                    detail="kept, but a value the model reported was not on the page",
                ))
            kinds[opp.source_kind] += 1
            out.append(opp)
            consecutive_errors = 0
            _emit_funnel(run, survivors=len(ranked), kept=len(out))
        except BudgetExceeded as exc:
            run.stop_reason = StopReason.BUDGET
            run.notes.append(f"BUDGET CEILING: {exc}")
            log.warning("Budget ceiling hit — %s", exc)
            break
        except Exception as exc:  # noqa: BLE001
            # One candidate failing to score must not discard the ones already
            # scored, or the ones after it.
            scoring_errors += 1
            consecutive_errors += 1
            # **The error goes where every other set-aside reason goes.** It used to be
            # a `log.warning` plus one line in `run.notes`, and nothing in the dashboard
            # renders either — so a run whose every triage call raised showed a stage box
            # reading "164 came in, 0 went through, $0.0000 spent" above the words
            # "Nothing was set aside at this step". The pipeline knew exactly what had
            # gone wrong 164 times and had nowhere to say it.
            #
            # Recorded against `phase`, so a failing triage is stage 2's problem and a
            # failing score is stage 3's, and carrying the exception text as the row's
            # detail — the same slot that holds "$4,000 < $10,000".
            run.reject(phase, "triage_error" if phase == 2 else "scoring_error",
                       funder=source.funder, title=candidate.title,
                       url=candidate.source_url,
                       detail=f"{type(exc).__name__}: {exc}")
            log.warning("  ! tier %d failed on %s — %r", phase, page.title[:40], exc)
            if scoring_errors == 1:
                run.notes.append(
                    f"Tier {phase} could not read {source.funder}: "
                    f"{type(exc).__name__}: {exc}"
                )
            # A circuit breaker, because the alternative is what happened: an expired key
            # or a bad model id fails identically on every candidate, and this loop
            # cheerfully walked all 164 of them one API error at a time. Nothing about the
            # 164th attempt was going to tell anybody more than the 5th did, and a run
            # that grinds through a whole funder list to produce nothing looks — from the
            # outside — exactly like a run that worked and found a quiet week.
            if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                run.stop_reason = StopReason.ERROR
                run.notes.append(
                    f"Stopped after {consecutive_errors} pages in a row could not be "
                    f"read. This is not a quiet week — something is wrong with the "
                    f"search itself, and the reason on each one is the same: "
                    f"{type(exc).__name__}: {exc}"
                )
                log.error("Stopping: %d consecutive failures at tier %d — %r",
                          consecutive_errors, phase, exc)
                break
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
    run.usd_by_stage = stage_costs(budget, cfg)
    return out


def stage_costs(budget: Budget, cfg: Config | None = None) -> dict[str, float]:
    """Split the run's spend across the three tiers, for the stage boxes.

    `Budget.by_model` already tracks spend per model; this is only the mapping from a
    model name to the tier it serves. Tier 1 is always 0.00 and is included anyway,
    because "the free tier is free" is the whole cost argument in CLAUDE.md §5 and a box
    with no cost line next to two that have one reads as missing data rather than as
    zero.

    Anything under a model we do not recognise lands on tier 3: an unexpected model is
    far more likely to be a scoring choice than a triage one, and over-attributing cost
    to the expensive tier is the safe direction to be wrong in.
    """
    from .score import SCORING_MODEL, TRIAGE_MODEL

    triage = (cfg.triage_model if cfg else "") or TRIAGE_MODEL
    scoring = (cfg.scoring_model if cfg else "") or SCORING_MODEL

    costs = {"1": 0.0, "2": 0.0, "3": 0.0}
    for model, spent in budget.by_model.items():
        # The two stages can legitimately be the same model — somebody who picks Sonnet
        # for triage as well. Then `by_model` has one entry for both and there is no way
        # to split it, so it lands on scoring: over-attributing to the expensive tier is
        # the safe direction, and the total is right either way.
        if model == triage and model != scoring:
            costs["2"] += spent
        else:
            costs["3"] += spent
    return costs


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


class RunInterrupted(Exception):
    """SIGTERM arrived: a deploy restart, systemd, or the Stop button.

    Raised from a signal handler so it lands in the ordinary `except Exception` around
    the crawl — which already exists to salvage a partial run — rather than killing the
    process where it stands.

    That distinction is worth real money. Without it, Python's default SIGTERM handling
    terminated the process outright: the salvage block never ran, and every opportunity
    scored so far was lost along with the API credit spent on it. A deploy at minute
    seven of a ten-minute run cost the org the whole run for nothing.
    """


def _install_stop_handler() -> None:
    def handle(signum, _frame):
        raise RunInterrupted(f"stopped by signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle)
        except ValueError:  # not the main thread — the caller owns signals
            log.debug("could not install a handler for %s", sig)


async def main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )
    # httpx logs every request at INFO, which drowns the run's own output — hundreds of
    # "HTTP Request: GET ... 200 OK" lines around the handful that say what happened.
    # It is also what the dashboard streams under the Re-run button, so the user was
    # reading raw request logs instead of progress. -v still turns it back on.
    if not args.verbose:
        for noisy in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _install_stop_handler()
    run = RunLog(started_at=datetime.now(timezone.utc))

    # Create and seed the settings database before reading config, so a first run picks
    # up the defaults from the same place every later run reads them.
    #
    # Deliberately NOT done under FUNDWORTHY_STRICT_CONFIG. Strict mode is the scheduled job,
    # where the database is not checked in — auto-creating it there would hand back a
    # fresh `enabled=1` on every run and silently defeat the kill switch, which is the
    # exact failure this guards against. In strict mode a config we cannot read stays a
    # refusal to run.
    strict = os.environ.get("FUNDWORTHY_STRICT_CONFIG", "").strip().lower() in {
        "1", "true", "yes", "on"}
    org_id = getattr(args, "org_id", None)
    if not strict and not args.no_archive:
        try:
            from app.db import init_db

            init_db()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not open the settings database (%s).", exc)

    try:
        cfg = load_config(org_id=org_id)
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

    # Step 0b: is there anything to read pages *with*. Before the crawl, for the same
    # reason the kill switch is before the crawl.
    #
    # This used to shrug and carry on with `use_llm = False`, which is the worst of both
    # worlds: a full crawl — every funder fetched, robots checked, politeness delays
    # observed, five to ten minutes of it — and then nothing scored at the end, because
    # scoring was never possible. The user pressed Search, waited, and got an empty list
    # with no explanation on it. Refusing up front costs them nothing and says which
    # single thing to fix. `--no-llm` is still the way to ask for the free tiers on
    # purpose, and it still works exactly as before.
    use_llm = not args.no_llm
    if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        run.stop_reason = StopReason.NO_API_KEY
        run.finished_at = datetime.now(timezone.utc)
        print(
            "No Claude API key, so there is nothing to read funder pages with — "
            "stopping before any page is fetched.\n"
            "  Fix it: open Settings in the dashboard and paste your key.\n"
            "  Or run with --no-llm to crawl and filter only, which costs nothing "
            "and scores nothing."
        )
        return 0

    budget = Budget(ceiling_usd=args.budget or cfg.weekly_budget_usd)

    # The monthly archive, both halves. The purge bounds the file; `already_seen` is
    # what keeps the user from re-reading the same grant every Thursday. Both are skipped
    # silently if there is no database — the agent still has to run from a fresh clone.
    already_seen: set[str] = set()
    if not args.no_archive:
        try:
            from app.archive import purge_old_months, seen_ids_this_month
            from app.db import init_db, session

            init_db()
            with session() as conn:
                run.purged_rows = purge_old_months(conn, org_id=cfg.org_id)
                already_seen = seen_ids_this_month(conn, org_id=cfg.org_id)
            if run.purged_rows:
                run.notes.append(
                    f"Archive: purged {run.purged_rows} row(s) from earlier months.")
            log.info("Archive: %d finding(s) already shown this month.", len(already_seen))
        except Exception as exc:  # noqa: BLE001
            log.warning("Archive unavailable (%s) — running without dedup.", exc)
            run.notes.append(f"Archive unavailable: {exc}")

    log.info("Crawling tier ≤ %d…", cfg.max_tier)
    opportunities: list[Opportunity] = []
    failed = False
    try:
        survivors = await crawl(cfg, run, follow_links=not args.no_follow,
                                already_seen=already_seen)
        log.info("%d candidates survived the free filters.", len(survivors))
        opportunities = evaluate(survivors, cfg, run, budget, use_llm=use_llm)

        # "Nothing was found" and "nothing was looked at" produce the same empty list
        # and mean completely different things. `sources_exhausted` on zero sources
        # reads as a quiet week; it is actually an empty funder list, which is the one
        # state where the app can do nothing at all until the user acts.
        if run.sources_attempted == 0:
            run.stop_reason = StopReason.NO_FUNDERS
            run.notes.append(
                "No funders to search. Fundworthy only reads the funders on your list, "
                "and yours has none that match the kinds of funding you have ticked. "
                "Add some on Discover funders."
            )
    except Exception as exc:  # noqa: BLE001
        # Whatever went wrong, the user still gets what we did find, plus a run log
        # saying it was incomplete. A silent empty Sheet on Thursday morning is
        # worse than a short one with an explanation on it.
        failed = True
        run.stop_reason = StopReason.PARTIAL if opportunities else StopReason.ERROR
        if isinstance(exc, RunInterrupted):
            # Not a failure of ours, and the distinction matters to whoever reads the
            # run log: the search was cut short from outside, and what it had already
            # paid for is written out below rather than thrown away.
            run.notes.append(
                f"Stopped early ({exc}). Keeping the {len(opportunities)} "
                "opportunit" + ("y" if len(opportunities) == 1 else "ies") +
                " already scored — the money spent on them is not wasted.")
            log.warning("Run interrupted — salvaging %d scored result(s)",
                        len(opportunities))
        else:
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
        sinks = []
        if args.sink == "sheets":
            from sinks.sheets import SheetsSink

            sheets = SheetsSink()
            sheets.ensure_config_tab()
            sinks.append(sheets)
        elif args.sink == "web":
            from sinks.webjson import WebJsonSink

            sinks.append(WebJsonSink(out_path=args.web_out))
        elif args.sink == "jsonl":
            from sinks.jsonl import JsonlSink

            sinks.append(JsonlSink(out_dir=args.out))
        else:
            # SQLite only. The dashboard reads the database through the API, which is
            # behind sign-in; run.json was a second copy of the same findings as a flat
            # file, and it used to be written into `dashboard/public/`.
            #
            # That directory is Vite's static-asset root: `npm run build` copies
            # everything in it into `dashboard/dist/`, which app/main.py serves to
            # anyone, unauthenticated, from the SPA catch-all. So the documented update
            # procedure — pull, rebuild, restart — was one step away from publishing
            # every org's grant pipeline at https://<host>/run.json. It was harmless
            # when the app only listened on 127.0.0.1. It is not harmless now.
            #
            # The sink still exists and still works; it is opt-in via `--sink web`, and
            # its default path is outside anything that gets served.
            from sinks.sqlite import SqliteSink

            sinks.append(SqliteSink(run_id=args.run_id, org_id=cfg.org_id))
    except Exception as exc:  # noqa: BLE001
        log.error("Could not open the %s sink: %r", args.sink, exc)
        return 1

    # Per sink, not per run: with two sinks a failure writing run.json must not cost
    # us the SQLite write that next week's dedup depends on. Whatever happens, we
    # still try to write a run log — a row saying the write failed is how the user finds
    # out, without having to call anyone (§13).
    written = 0
    for sink in sinks:
        try:
            written = max(written, sink.write_opportunities(opportunities, run))
        except Exception as exc:  # noqa: BLE001
            failed = True
            run.stop_reason = StopReason.PARTIAL
            run.notes.append(f"WRITE FAILED ({sink.name}): {exc!r}")
            log.exception("Writing opportunities to the %s sink failed", sink.name)

    for sink in sinks:
        try:
            sink.write_run_log(run)
        except Exception as exc:  # noqa: BLE001
            log.error("Could not write the run log to %s: %r", sink.name, exc)

    print(f"Wrote {written} records via: {', '.join(s.name for s in sinks)}.\n")
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="the organization funding opportunity agent")
    p.add_argument("--sink", choices=["db", "web", "jsonl", "sheets"], default="db",
                   help="db (default) writes SQLite, which is what the dashboard "
                        "reads; web writes a static JSON file; sheets is export-only")
    p.add_argument("--run-id", help="attach this run's findings to an existing run row")
    p.add_argument("--org-id", default=None,
                   help="whose search this is: the org whose settings, program cards, "
                        "funders and API key the run uses, and the org its findings are "
                        "written to. Defaults to the single-tenant org.")
    p.add_argument("--no-archive", action="store_true",
                   help="skip the monthly dedup and purge (shows repeats again)")
    p.add_argument("--out", default="out", help="output dir for the jsonl sink")
    p.add_argument("--web-out", default="data/run.json",
                   help="output path for the optional static JSON export. NOT under "
                        "dashboard/ — see --sink.")
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
    p.add_argument("--balance", type=int, metavar="N",
                   help="take up to N from funder pages AND N from indexed databases, "
                        "instead of one combined cap")
    p.add_argument("-v", "--verbose", action="store_true")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
