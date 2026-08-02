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

## Sun Aug 2, 2026 — v2, after the stakeholder follow-up

Full reasoning in `docs/PLAN.md` §0. The decisions, and what each one cost:

| # | Decision | Rationale | What we gave up |
|---|---|---|---|
| B1 | **Local FastAPI + SQLite**, not a static site and not a hosted service. | Everything she asked for — an API-key box, CRUD, an archive, a re-run button, an AI assistant — is impossible on a static page. Local means no hosting bill, no deploy to break mid-demo, and no public endpoint holding a key. | She cannot open it from her own laptop until someone installs it. Written up honestly in HANDOFF.md rather than glossed. |
| B2 | **Reverse `CLAUDE.md` §3**: config moves into the dashboard. | A spreadsheet cell cannot express "search these three programs, with these terms, at this floor, this week". The non-goal was written before we knew she wanted a control surface. | The "she never leaves Sheets" simplicity. Mitigated by keeping `sinks/sheets.py` as an export. |
| B3 | **Demote the Sheet** from "the product" to an export target. | Follows from B2 — two sources of truth for config is worse than either one alone. | The "if everything else dies she still has her data" argument, partly. The DB is one file she can copy, which is the closest honest equivalent. |
| B4 | **Programs become editable cards; the scoring prompt is generated from them.** | RISE has seven programs, not three, and the three-value enum made adding one a code change. Generating `org_context` from the cards means a program added Sunday is searchable Wednesday. | A byte-stable prompt across runs. Still stable *within* a run, so caching is unaffected. |
| B5 | **The card assistant reads a link instead of taking a prompt.** | §2 forbids any workflow where she phrases a request to an AI. Reviewing a filled-in draft about her own programme is a job she can actually check; composing a prompt blind is not. | Nothing. This is strictly better than the textarea it replaced. |
| B6 | **Seed the four non-priority programs EMPTY.** | We only had names and URLs. Writing plausible descriptions of a real organisation's programmes is the same failure §6 forbids for award amounts. | A demo that looks more complete out of the box. Worth it — and it makes the assistant's value obvious. |
| B7 | **Sourced vs inferred fields are visually distinct.** | Mauri asked for funder type, service areas, and a confidence %. None of those can be quote-gated. Rendering them identically to a sourced award amount would quietly break the §6 promise at the UI layer. | Some visual noise. `.chip.inferred` is marked in the CSS as a correctness requirement so it survives the redesign. |
| B8 | **Monthly purge, deliberately blunt.** | Bounds the file and stops her re-reading the same grant. A grant seen in July resurfacing in August is intended, not a bug — it may still be open. | Long-term history. The row count purged is logged so it is never silent. |
| B9 | **Re-run is a subprocess, not a thread.** | Stop has to actually stop, and §8 promises her a kill switch. A thread mid-`httpx` call cannot be interrupted; a process can. Bonus: identical code path to the cron. | Slightly more machinery than an in-process call. |
| B10 | **Encrypt the API key at rest; never return it.** | §2 said she never sees an API key. §11 Q6 means someone at RISE must hold one. Write-only in one box is the smallest surface that satisfies both. | Not much. The threat model (shared DB file, screenshot, bug report) is stated honestly in `app/secrets.py` — it is not defence against a compromised machine. |
| B11 | **Build only the discovery *seam*; the provider is the teammate's branch.** | Two people writing beyond-the-partner-list search is wasted work and a guaranteed merge conflict. | The checkbox does nothing yet — and says so, rather than failing silently. |

### Corrections we made to our own work

- **`MIN_AWARD` $25,000 → $10,000.** Not a tweak: the placeholder was a guess we had
  loudly labelled as one, and the real number came from the stakeholder. All the
  placeholder machinery came out with it.
- **The "~16 hours a week" stat was deleted from every file**, including
  `agent/score.py`'s prompt, where it was being asserted to the model as fact about a
  real person on every scoring call. RISE says the figure is wrong. Logged as an open
  question rather than replaced with another guess.
- **E12 — we were wrong about a win.** The accuracy gate fired on live data and we
  nearly wrote it up as "caught two confabulations". Checking the pages first showed the
  model was right and our parser was mangling `$150,000` into `$\n150\n,\n000`. The gate
  was discarding *true* values. Fixed both halves; records with a sourced amount went
  0 → 1 on the same crawl.

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
