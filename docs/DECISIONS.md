# Decision Log — RISE Fund Finder

Running record of the architecture calls we make and why. Doubles as rubric evidence
(Use of AI → Transparency; Execution → Evidence package / decision log).

Format: decision · date · rationale.

## Sat Aug 1, 2026 — tech-stack review (post multi-agent review of CLAUDE.md)

| # | Decision | Rationale |
|---|---|---|
| A1 | Add a **verbatim-quote + deterministic substring verify** on every deadline/award before it's marked `verified`. Fail → null the field + `needs_human_check`. | `source_url` only proves a page was fetched; a confabulated number is the "fatal in demo" case the flag never catches. Reuse `parse.py`'s `Evidence` snippets as the source of truth. |
| A2 | Fetch-health guard (visible-text-length + deadline-keyword) → don't parse, flag for human. Curate registry toward static deep URLs. **Reject** headless browser. **Defer** PDF (`pypdf`) until the curated list proves PDF-heavy. | Static fetch silently returns empty on JS/portal pages. We never store pages/PDFs — only extracted fields + URL, so no storage bloat. |
| A3 | Pin exact dated model IDs in one config constant; look them up via the `claude-api` skill, never hardcode from memory. | Unpinned aliases drift between calibration and the cron run; a wrong-but-plausible ID is its own landmine. |
| A4 | Add prompt caching (one `cache_control` breakpoint on the static prefix). | Every scoring call reshares the same big instructions; caching cuts repeat input cost. Protects the $1 ceiling on a spike week. |
| A5 | **Reject** Batch API for v1; park in HANDOFF as a 30-day cost optimization. | Fire-and-forget defeats the live $1 mid-run abort and can't be demoed live. |
| A6 | Dashboard = **Opt 2** (static `run.json` the Action commits, read by a custom React UI). Kill the serverless-reader. | No public credentialed endpoint; no live-API failure mid-demo; we want a custom UI to refine later with Claude design. |
| A7 | Keep GitHub Actions cron + `workflow_dispatch` + explicit UTC + DST note. | Cheapest zero-server scheduler, versioned with the code. |
| A8 | Harden kill switch: `timeout-minutes` on the job + fail-closed config load. | `ENABLED` only reads at step 0; guard the runaway + unreadable-config cases. |
| T4 | Drop to one parser where practical; keep gspread with batched single append + local JSON artifact before the Sheets write. | Remove untested fallback surface; the artifact doubles as evidence. |
| C | Ship the A1 gate first (Sat night); capture calibration before/after + `/evidence` during the build; fix model-ID + dashboard contradictions before freeze. | ~20 of our 55 Execution+Use-of-AI points + the demo spine. |

## Ownership split
- Phyo + teammate own **Execution (30)** and **Use of AI (25)**.

## Resolved — Sat night
- **Q-base:** Build on top of `origin/dev` (teammate's MVP). Working branch `phyo-build` off `origin/dev`.
- **Q-scope:** RISE-only for now. No multi-tenant accounts / DB. Results served from a committed `run.json` (A6 Opt 2).
- **Q-delivery:** **Website + Gmail-export ONLY** — no service-account auto-write. The website is Mauri's supervise-and-prune surface: she reviews the agent's results, prunes the ones she doesn't want, then exports the curated shortlist to her Google Sheet via her OWN Gmail OAuth (Sheets scope; she is a listed test user until the OAuth app is verified).
  - Risk owned by team: this moves Mauri off Sheets-as-primary and adds OAuth (both were spec non-goals). Mitigation: get a quick "a website works for me" from Mauri; the pruning step is the human-in-the-loop justification.

## Build order (from Sat night)
- Phase 0 (delivery-independent): fix + run the LLM tier (correct model IDs, verify SDK call shape), wire the A1 accuracy gate, calibration before/after.
- Phase 1: agent emits committed `run.json` the site reads; retire service-account auto-write from the weekly flow.
- Phase 2: website results view + keep/reject prune UI.
- Phase 3: Google OAuth (Sheets scope) + "export selected to my Sheet".

## Found in teammate's `dev` MVP (Sat night review)
- Already implements A7 (workflow_dispatch, UTC, concurrency) and A8 (timeout + fail-closed) — ahead of spec.
- A1 gate NOT wired: scored numbers come from the model unverified. `parse.py` has the `Evidence` snippets to verify against.
- LLM tier untested (`usd_spent: 0.0` in every evidence run). `SCORING_MODEL` was `"claude-sonnet-5"` (a nonexistent ID that would 404) — **fixed to `claude-sonnet-4-6`** via the claude-api skill; triage stays `claude-haiku-4-5`. Cache-min gate corrected 1024 → 2048 (Sonnet 4.6). Still needs a real run with a key to prove the tier end-to-end.

## Progress — Sat night build (branch `phyo-build`)
- **Scoring model:** confirmed **Sonnet 4.6** (flagship Sonnet) for final scoring; Haiku 4.5 for triage. There is no "Sonnet 5" — `claude-sonnet-5` was a hallucinated ID.
- **A1 accuracy gate — DONE.** `agent/verify.py` (`quote_on_page` + `year_in_quote`) wired into `score_one`: the model must return the verbatim source sentence for any award/deadline; unverifiable → nulled + `needs_human_check`. `tests/test_accuracy_gate.py` passes 13/13 offline (no key).
- **Phase 1 data path — DONE.** `sinks/webjson.py` (`--sink web`, now the default) writes `dashboard/public/run.json` (public-safe allowlist). `dashboard/src/App.jsx` repointed from the serverless `/api/runs` reader to `/run.json` and renders the results. Retired: `dashboard/api/runs.js` (unused; safe to delete).
- **Deferred:** `weekly.yml` → `--sink web` + commit step; the config/kill-switch location in the website-first design; Phase 2 (prune UI); Phase 3 (Gmail OAuth export).
- Manual verification: `docs/TESTING.md`.
