# FUTURE.md — Fundworthy roadmap

Everything Fundworthy is *not* yet but is meant to become. [CLAUDE.md](CLAUDE.md) is the
present tense (what's built and working); this file is the future tense. Move an item
here into CLAUDE.md only once it actually ships.

---

## 0. The vision

Fundworthy started as a tool for one nonprofit. The problem it solves — "searching for
funding eats hours and most of what you find is too small to be worth applying for" — is
not unique to that org. The goal is to make Fundworthy **available to any nonprofit, at
no cost to us to operate**.

Two decisions make "free for everyone" actually true rather than aspirational:

| Decision | Why it makes free possible |
|---|---|
| **Bring-your-own-key (BYO-key)** — each org pastes its own Anthropic API key | Inference is the only real cost, and it's the one that grows per org. BYO-key pushes it onto each tenant, so our operating cost stays ≈ one small server. |
| **Oracle free VM (compute) + managed free Postgres off-box** | Stays free, but the database is backed up by the provider and the single-point-of-failure shrinks to stateless compute we can rebuild in minutes. |

The thing to keep repeating: **hosting is the cheap part.** A free VM saves ~$5–40/mo.
The Anthropic bill, at scale, is 10–100× that — which is exactly why BYO-key is the
architecture, not a detail.

---

## 1. Where we actually are

The app is **live on the internet** on an Oracle Always-Free ARM VM, behind nginx +
certbot TLS, with Google sign-in via Firebase and an `ALLOWED_EMAILS` allow-list. (The
hostname and the box's address are in [docs/ACCESS.md](docs/ACCESS.md) rather than here —
this repository is public, and a live box's IP in a public file invites the scanning you
would rather not attract.) That crossing — from a localhost-only,
single-tenant tool to a shared, public one — invalidated a set of assumptions the codebase
was, quite legitimately, built on. This file is now mostly about closing that gap.

**Shipped since going live:**

- Sign-in (§2).
- **Tenant isolation** (§3) — orgs, per-org data, per-org API keys, colleague invites.
- The `run.json` exposure path, the interrupted-run zombie rows, the cross-org Stop
  button, and seed resurrection (all §3).
- **SSRF in the fetcher** (§5) — public addresses only, checked per redirect hop.
- **Push-to-deploy** (§6) — drain, wait for in-flight runs, back up, test, restart.
- **The geography filter reads `org_location`.** It was hardcoded to San Diego, which
  made the setting a lie: a Chicago nonprofit could type "Chicago, Illinois", watch it
  save, and still have every Illinois-only grant rejected for free in the tier that never
  explains itself. The vocabulary of *places* is universal and lives in code; which of
  them is **yours** is configuration. An org that has not said where it works now rejects
  nothing on geography rather than inheriting somebody else's region.

**The one thing to do before anything else** is not code: see §8, *Access and bus factor*.

---

## 1a. Prioritized backlog — engineering audit (2026-08-06)

Everything below §2 is the full record, written as each thing was found or shipped. This
section is a fresh pass on top of it: every `.py` and `.jsx` file in `app/`, `agent/`,
`sinks/` and `dashboard/src/` read closely against what CLAUDE.md and the rest of this file
claim is true, looking specifically for what neither document had caught yet. Every item
below was confirmed against the actual cited file and line before landing here — nothing
is inferred from a docstring or a comment alone. It sits **alongside, not above,** §8's
access-and-bus-factor problem, which stays first because it isn't fixable by writing code,
and because everything else here assumes there is more than one person able to restart the
service if a fix goes wrong.

### P0 — ✅ shipped (2026-08-06)

Four things, and the common thread was that each one silently defeated a guarantee this
product is explicitly sold on, in code that was live at the time. All four are fixed, each
with a regression test that fails on the old code — see CLAUDE.md §2 and §7 for the
present-tense description of what changed and where the tests live.

1. ~~**The Block button does nothing.**~~ **Fixed.** `FunderIn` had no `blocked` field, so
   Pydantic silently dropped it from the request body and `PUT /api/funders/{id}` returned
   200 having changed nothing — `repo.update_funder` already handled `blocked` correctly, the
   field just never arrived. Added `blocked: bool | None = None` to `FunderIn`
   (`app/main.py`). `tests/test_api.py::test_blocking_a_funder_through_the_api_actually_persists`
   goes through the real HTTP layer specifically because every existing test called
   `repo.update_funder` directly and would never have caught a request-model gap.
2. ~~**A caught, unlogged exception could serve one org a different org's funder list under
   a false note.**~~ **Fixed.** `sources_from_db` now logs (`log.error`, with traceback) when
   an *existing* database fails to read, instead of returning `None` silently and
   indistinguishably from "no database file yet". `resolve_sources` (`agent/run.py`) checks
   which case it was and writes an honest run note either way — "could not read the funders
   list" rather than the false "no funders database found". Covered by
   `tests/test_db.py::test_a_broken_funders_table_is_logged_not_silently_swallowed` and
   `::test_a_read_error_gets_an_honest_run_note_not_no_database_found`.
3. ~~**`apply_filters()` had zero direct tests.**~~ **Fixed.** New `tests/test_filters.py`
   (12 tests) covers the award floor, the null-vs-reject distinction the module docstring
   calls the entire product, the deadline runway, the religious/political/not-an-opportunity
   rejects, the match-requirement flag, and the per-program floor. Writing it surfaced one
   more thing, filed separately below: `Reject.DEADLINE_PASSED` turns out to be unreachable
   through a real `ParsedPage`.
4. ~~**The "no URL, no record" rule had no test that constructs a bad record and checks it's
   rejected.**~~ **Fixed.** Four new tests in `tests/test_accuracy_gate.py` construct an
   `Opportunity` with a missing, empty, and scheme-less `source_url` and assert
   `__post_init__` refuses all three, plus one confirming a real `http(s)://` URL is accepted.

### P1 — significant risk or real cost, next after P0

**Carried forward, still true, detailed in their own sections:** no roles within an org
(§2, §3), the allow-list living in an env var with no audit trail or revocation (§2),
per-minute rate limiting still missing on `POST /api/runs` and `POST /api/programs/draft`
(§5), `data/.fernet-key` sitting next to `data/rise.db` (§5), and run state living in one
process's memory as the thing actually blocking a second uvicorn worker (§3, §9).

**New from this pass:**

- **A second hardcoded-San-Diego leak, in the one feature CLAUDE.md calls "the answer to
  the user never writes a prompt."** `app/assistant.py`'s `SYSTEM` prompt opens "You are
  helping the COO of the organization, a nonprofit in San Diego and Imperial Counties..." as
  a literal string; `draft_program_card` takes no org context, and its only caller
  (`app/main.py:391`) never passes `org_name`/`org_location` even though it already resolves
  the org. This is the exact bug class §5 describes at length for `agent/score.py`'s
  `_preamble` and says was fixed there — the fix was never applied here.
- **The cost ceiling undercounts real spend once prompt caching is active.**
  `Budget.record()` (`agent/score.py:854`) only reads `usage.input_tokens`/`output_tokens`;
  it never reads `cache_creation_input_tokens` or `cache_read_input_tokens`, even though the
  scoring prompt now routinely clears the caching threshold. Cache-write tokens bill *above*
  the base input rate — so the tracked `spent_usd` a run's budget check gates every
  subsequent call against is an underestimate, meaning a run can spend more real dollars than
  the $1 ceiling before anything notices. This works directly against the "no exceptions"
  framing in §5.
- **A run that fails leaves nothing to explain why, which is the one case the log exists
  for.** Two compounding gaps. The second is **fixed (2026-08-07)**: the "technical log"
  CLAUDE.md calls "still the only thing that explains a run that died halfway" was
  in-process memory deleted the instant the child's stdout closed, so it was empty for
  every finished run — it is now persisted to `runs.log_tail` (v16, last 200 lines) and
  served by `GET /api/runs/current`, fetched on demand when the disclosure is opened.
  Reported from the live site by the user opening it after a run and finding nothing.

  **Still open:** `write_run_log`'s failure path (`agent/run.py`) only logs and never marks
  the run as failed, so a broken sink write still exits 0 and the dashboard shows a "done"
  run with blank stats and no stop reason.
- **A funder's retry backoff hits the exact host that just asked to be left alone, harder.**
  `Fetcher.get()`'s retry loop (`agent/fetch.py:167`) re-walks the *entire* redirect chain
  from the original URL on every attempt instead of resuming from the failure, so a 429/503
  on the final hop of a two-redirect page turns "two retries" into up to nine real requests —
  worst exactly when the server has just signalled it's overloaded, against this same file's
  own stated design goal of being a polite, small-nonprofit crawler.
- **Unsaved edits in "Adjust search settings" — the panel CLAUDE.md says the dashboard was
  reversed for — are silently wiped by any unrelated action on the same page.**
  `Dashboard.jsx:84`'s `useEffect(() => setDraft(state.settings), [state.settings])` fires on
  every poll refresh, because `state.settings` is a new object reference every time
  regardless of whether values changed. Ticking a program chip elsewhere on the page while
  the settings drawer is open silently snaps unsaved input back to the stored values, with no
  warning. `Settings.jsx`'s `OrgPanel` gets this right by depending on the individual field
  values instead of the object reference — the fix is to match that pattern here.
- **Turning on org-wide funder sharing from Settings skips the confirmation dialog that the
  same toggle requires from Discover.** `Settings.jsx`'s `ShareFunders.toggle` saves directly
  on click; `Discover.jsx`'s `Contribute.toggle` gates the identical action behind a
  three-point confirm dialog, and a comment above it claims the two match. They don't — a
  user who finds the setting via Settings rather than Discover starts publishing their
  funder list with one unconfirmed click.
- **The shared-funder report endpoint has no plausibility check, so one account can script a
  wipe of the platform-wide shared directory.** `report_shared_funder`
  (`app/repo.py:765`) only checks for a duplicate report from the same reporter — never that
  `(funder_org, funder_id)` names something currently offered. `GET /api/directory/shared`
  returns exactly the pairs needed to do this; loop GET → report-every-row → GET again and
  the pool empties in seconds. Combined with `FUNDWORTHY_ADMIN_EMAILS` being unset by default
  (documented in §2 as normal), an install with no admin configured has no way to undo it.
- **The dashboard has no test tooling at all, and the team's own comment shows this already
  shipped a white page to production.** `dashboard/package.json`'s `devDependencies` are only
  `vite` and `@vitejs/plugin-react` — no runner, no assertion library — and CI's only
  frontend step is `npm run build`. `tests/test_dashboard_sources.py`'s own docstring
  documents the incident: a missing import shipped past a green build and 300 passing Python
  tests, and "the first person to press 'Adjust search settings' on the live site got a white
  page." The fix that landed is a regex scan for undeclared JSX identifiers, with the same
  docstring noting "a real ESLint setup would be better and is worth doing" — that's still
  open, and neither it nor an actual component-level test exists for any of the ~4,300 lines
  in `dashboard/src/components/`.
- **`RunManager.start()`'s actual subprocess-launch path has never been exercised by a
  test.** Every existing test hits a `RuntimeError` inside the lock before reaching
  `subprocess.Popen` (`app/runner.py:386`) — nothing verifies the API key lands in the child's
  environment and never in argv (the property the module's own docstring calls out as the
  reason it's done that way), or that two different orgs' slots don't collide.
- **The California Grants Portal and Grants.gov integrations — core seed sources per
  CLAUDE.md — have no test coverage on the code that actually calls them.**
  `fetch_ca_grants_portal` and `fetch_grants_gov` (`agent/apis.py:166`, `:343`) and their
  parsing helpers (`_first`, `_structured_amounts`, `_deadline_evidence`) are never invoked by
  any test. `_first`'s own docstring names the exact failure mode a test would need to catch —
  "a renamed field returns 200 with a null where the money used to be" — and nothing checks
  that it actually survives one.

### P2 — moderate, worth scheduling

**Carried forward:** no incremental persistence mid-run (§6, mitigated by SIGTERM handling),
no shared cross-tenant fetch cache (§9), the vite/esbuild dev-dependency `npm audit` findings
(§5), no nginx request-size or rate-limit configuration (§5).

**New from this pass:**

- `update_run` (`app/repo.py:516`) is the one function in `repo.py` with no `org_id`
  parameter — the module otherwise enforces it as a required keyword everywhere, per
  CLAUDE.md's own stated rule that a missing one should be a `TypeError`, not a silent gap.
  It also builds its `UPDATE` column list from unvalidated `**fields` keys rather than an
  allow-list, unlike every sibling writer in the file. No call site passes an
  externally-influenced `run_id` today, but there's no type-level guard stopping one from
  starting to.
- `redeem_invite` (`app/db.py:1126`) resolves the caller's existing account with
  `WHERE uid=? OR email=?` and `fetchone()` — if a uid and a separately-reused email each
  match a *different* row (the exact "deleted and remade the Google account" scenario the
  surrounding docstring anticipates a few lines up), the OR is ambiguous and can silently
  move or strand the wrong account. `org_for_user` in the same file avoids this correctly
  with two sequential lookups instead of one combined `OR`.
- `shared_funders` — the query behind Discover's cross-tenant funder panel — filters on
  `added_by`, `check_ok` and `f.org_id <> ?`, none of which the table's only index
  (`idx_funders_org`, on `org_id` alone) can narrow; an inequality on the one indexed column
  makes it a full scan of every org's funders on every page load. A partial index on
  `(added_by, check_ok) WHERE added_by='user' AND check_ok=1` fixes it.
- The v7 org-scoping migration's per-table copy-then-drop (`app/db.py:891`) runs as separate,
  non-atomic statements after the schema `executescript()` that already forced a commit. A
  crash between them leaves an orphaned `<table>__pre_org` shadow table that a later boot's
  skip check can never detect (it only inspects the live table's columns) — silently
  defeating the retention guarantees §3 documents for org deletion, for any row that predates
  this migration.
- `update_program` and `update_funder` (`app/repo.py:202`) each hand-roll a near-identical
  dynamic-`UPDATE` builder with separate field lists and inline boolean/JSON coercion. The
  comment at `update_funder`'s `blocked` branch explicitly recalls a real bug this exact
  duplication already caused once (a boolean stored as the string `"True"` instead of `1`) —
  the next new column on either table has to get the same branching right a third time, with
  nothing enforcing it.
- The CSP allows `'unsafe-inline'` for `script-src` (`app/main.py:1215`) even though the
  built dashboard has exactly two inline `<script>` blocks, both static and known at build
  time (a JSON-LD block, a theme-flash-prevention snippet). Hash-pinning them (or moving the
  theme snippet to an external file under `'self'`) closes the one meaningful gap in the
  header this app relies on as its XSS defense-in-depth.
- Adding a shared funder (`dashboard/src/pages/Discover.jsx:139`) copies the contributing
  org's freeform `notes` field into the receiving org's record without ever displaying it —
  the card only renders `evidence` and `checked_at`. That's an unreviewed, unbounded string
  moving across a tenant boundary on one click, against the "evidence, never a verdict"
  design §2 (Pilot / seed data section of CLAUDE.md) states as this feature's whole safety
  property.
- No global FastAPI exception handler exists, and the log format carries no request or org
  id (`app/main.py:1154`). Several endpoints (`read_settings`, `list_programs`,
  `list_funders`, `list_opportunities`, `read_archive`, and others) have no try/except of
  their own, so an unexpected exception in any of them never reaches this app's own logger —
  only wherever uvicorn's default handling happens to print it.
- The three live-progress writers behind the spend marker and stage-box rails
  (`app/runner.py:501`, `_write_spend`/`_write_funnel`/`_write_progress`) fail silently at
  `log.debug`, but production logging is configured at `INFO` (`app/main.py:1164`) with no
  per-logger override — so a recurring write failure (lock contention from concurrent orgs,
  a nearly-full disk) stops the live UI from updating for a whole run with zero trace in the
  logs an operator would ever see.
- ~~The per-candidate scoring loop catches every exception the same way with no circuit
  breaker and no tracking of *consecutive* failures.~~ **Fixed (2026-08-07), and it was
  live, not hypothetical** — a real run triaged 164 candidates, failed on every one, and
  reported "0 went through / $0.0000 spent" beside "Nothing was set aside at this step".
  Three changes: the exception is now a reject row (`triage_error` / `scoring_error`)
  against whichever tier was running, carrying the exception text as its detail;
  `CONSECUTIVE_ERROR_LIMIT` (five) ends the run as `error` rather than walking the whole
  list; and `run.notes` is finally rendered on This week. Covered by
  `tests/test_pipeline_reporting.py` (five of its tests fail on the old code).
- **Stage 1's headline number and its own breakdown counted different populations** —
  found in the same session, from the same run, and **fixed (2026-08-07)**. Rejects made
  inside an API adapter went into `rejected_by_filter` but never into
  `candidates_parsed`, so the box reported "47 set aside" above a list whose first two
  rows summed past 118. `crawl()` now counts an adapter's refusals as candidates
  considered, which is what they are.
- `evaluate()` (`agent/run.py:484`) drives Haiku triage and Sonnet scoring strictly serially
  through blocking synchronous calls, discarding the concurrency `crawl()` built up — and a
  fresh `anthropic.Anthropic()` client is constructed per call (`agent/score.py:761`) rather
  than once per run, paying a new TCP/TLS handshake on every one of dozens of calls. Together
  these inflate wall-clock time well past what candidate count or the budget ceiling would
  otherwise require, and a longer subprocess is more exposed to the mid-run SIGTERM case §6
  already treats as a real, costly failure mode.
- Full page text is held uncapped in memory from `parse_page()` through the entire
  evaluation loop (`agent/parse.py:131`) — the only place it's ever bounded is a fresh slice
  taken per-call deep inside `score.py`'s prompt building. A wide crawl touching several large
  pages can hold multiple megabytes of text no model will ever read, on the resource-
  constrained free-tier VM this is deployed to.
- The robots.txt preflight (`agent/fetch.py:159`) runs before the per-host lock is acquired,
  so concurrent `get()` calls for the same host race to fire simultaneous robots.txt
  requests on the first crawl touching it — confirmed reachable today: several hosts in
  `agent/sd_funders.py` (e.g. `www.bscc.ca.gov`) have multiple funder URLs that would trigger
  it.
- `WebJsonSink._month_rows` (`sinks/webjson.py:101`) calls `repo.list_opportunities(conn)`
  without the now-required `org_id` keyword — every call raises `TypeError`, which a bare
  `except Exception: return None` (intended only to catch "no database yet") swallows
  silently. `write_run_log` then always falls back to just this run's own output, never the
  month's archive, defeating the exact fallback the surrounding docstring says it exists to
  avoid. Low-traffic today since `--sink web` is opt-in, but genuinely broken.
- `sinks/webjson.py` and `sinks/jsonl.py` have no test coverage at all — no test file
  imports either module — despite `webjson.py` owning the `PUBLIC_FIELDS` allowlist that
  keeps a non-public `Opportunity` field from leaking onto the unauthenticated public site,
  and non-trivial archive-vs-run-only fallback logic.
- `draft_program_card`'s actual Anthropic-call path (`app/assistant.py:150`) — the code
  behind "the user never writes a prompt" — is never executed by any test; every existing
  test stops at the pre-flight "no API key" or duplicate-URL check. The response-truncation
  logic, cost math, and error-message mapping are all untested and could regress silently.
- Two of the app's three modal dialogs (`StageDetail.jsx`, `ModelPicker.jsx`) have no
  keyboard focus trap — only `Confirm.jsx` implements one, with a comment explaining exactly
  why it matters ("Tab walks out of the dialog... a screen-reader user is answering a
  question they can no longer see"). The other two reuse the same `aria-modal="true"` markup
  without the behavior it claims.
- Switching months quickly on the archive page (`Archive.jsx:30`) can display the wrong
  month's findings: the fetch effect has no live/cancellation guard, unlike `App.jsx`'s
  `refresh()`, which uses one for the same reason. Two in-flight requests race and whichever
  resolves second wins, even if it's for a month no longer selected.
- A transient failure loading org membership permanently disables the close-account
  confirmation with no error shown and no retry (`Settings.jsx:744`) — `DeleteAccount`'s
  mount effect swallows the error and leaves the confirm button disabled with nothing
  explaining why, for the rest of that page load.

### P3 — minor, worth a cleanup pass

- **Stage 1 still does not reconcile *exactly*, and the remaining gap is duplicate URLs.**
  The big divergence (adapter rejects counted in one column and not the other) is fixed, but
  `consider()` in `agent/run.py` increments `candidates_parsed`, then returns early on
  `if page.url in survivors` **without recording a reject reason** — a page reached twice in
  one run (two funders linking the same grant, a redirect landing on an already-seen URL)
  raises "came in" without raising either "went through" or any row in the breakdown. So
  `parsed − survivors` can still exceed the sum of the reasons by the number of intra-run
  duplicates. Small, and in the honest direction (it over-reports what was set aside rather
  than hiding it), but it is the last thing keeping the two halves of that box from adding
  up. Wants either its own reason (`already_seen_this_run`) or not counting a duplicate as a
  candidate at all — the first is better, since it is a real thing that happened.
- **A count-only reject group is hardcoded to stage 1** (`app/main.py:782`,
  `groups.append({"reason": key, "stage": 1, ...})`). That is correct for the case it was
  written for — an API adapter aggregates its own rejects, and those genuinely are
  free-tier — but it is right by coincidence rather than by derivation. `run.rejects` is
  capped at `MAX_REJECTS` (400) while `rejected_by_filter` counts without limit, so on a
  run that exceeds the cap *any* reason whose rows were truncated away becomes a
  count-only group and gets filed under stage 1 regardless of the tier it came from —
  putting a triage or scoring failure in the free-filters box. The reason needs its stage
  carried alongside the count rather than inferred from whether a row survived.
- **`Reject.DEADLINE_PASSED` is unreachable through `apply_filters()`.** Found writing the
  new filter tests above, not by the original audit pass. `ParsedPage.earliest_deadline`
  (`agent/parse.py:148`) only ever returns a date `>= date.today()` — a page whose only
  deadline evidence is in the past resolves to `None`. So in `apply_filters`
  (`agent/filters.py:198`), `deadline` can never be in the past, `days < 0` can never be
  true, and the `Reject.DEADLINE_PASSED` branch can never fire via a real parsed page. The
  practical effect: a page whose only stated deadline has already passed is flagged
  `DEADLINE_NOT_STATED` (a human-reviewed flag, still costs a triage call) rather than freely
  rejected — which may be the right call if a page can legitimately roll over to an
  unpublished next cycle, or may just be dead code nobody meant to leave unreachable. Worth a
  product decision, not a silent fix.
- `geography_ok` (`agent/filters.py:140`) references `UNIVERSAL_GEOGRAPHY` and
  `GEOGRAPHY_RESTRICTION` — names defined nowhere in the codebase — and has zero callers;
  calling it raises `NameError`. It sits directly beneath the comment explaining that
  geography filtering was deliberately removed (§ note at the top of `agent/filters.py`),
  and looks like a partial revert left behind by that removal. `summarize()` in the same file
  is separately dead. Delete both.
- `apply_filters()` builds a `haystack` string (`agent/filters.py:168`) on every page and
  never reads it again — a small wasted allocation and a sign of an incomplete refactor.
- `model_label` (`agent/score.py:81`), `row_to_dict` (`app/db.py:1297`) and `utcnow`
  (`sinks/sheets.py:379`) each have zero call sites anywhere in the repo, including tests.
- `idx_users_org` is created twice — once inline in `SCHEMA` (`app/db.py:92`), once again in
  the separate `INDEXES` block — contradicting the comment explaining why org-referencing
  indexes were deliberately moved out of `SCHEMA` in the first place. Harmless (`IF NOT
  EXISTS`), but misleads anyone auditing `INDEXES` for a full inventory.
- `sinks/sqlite.py:40`'s `_ready()` re-runs the *entire* `init_db()` — schema script, full
  15-step migration walk, index script, and an unconditional `ensure_org(DEFAULT_ORG_ID)` —
  before every single write, so one run opens four connections where one preflight check
  would do, and touches the default org's row even when writing for a different org.
- `open_reports()` (`app/repo.py:792`), the admin moderation queue, has no `LIMIT` or
  pagination on a query any signed-up org can grow via `report_shared_funder`.
- Several redundant local re-imports of names already in scope at module level
  (`app/repo.py:774`'s `hashlib`/`now_iso`, `agent/apis.py:496`'s `re`) — harmless, but
  indistinguishable at a glance from the handful of local imports elsewhere in these same
  files that exist for a real circular-import reason.
- `ApiKeyTestIn.api_key` (`app/main.py:139`) has no `max_length`, unlike its sibling
  `ApiKeyIn.api_key` (bounded to 500 chars) — `POST /api/settings/api-key/test` forwards an
  unbounded string straight into an outbound Anthropic call.
- `app/assistant.py:177` catches `AuthenticationError` and `APIStatusError` but not
  `APIConnectionError`/`APITimeoutError` (siblings under `APIError`, not subclasses of
  `APIStatusError`) — a network blip surfaces a raw Python exception class name
  ("The assistant could not finish (APIConnectionError).") to a user CLAUDE.md's binding
  design constraint says has no AI experience and should never see one.
- `app/stats.py` (the `python -m app.stats` ops CLI) is untested and reads
  `repo.platform_stats()`'s dict via bare bracket access with no `.get()` — a shape change
  would only surface when someone runs it by hand, per the module's own docstring, "at 2am."
- The landing page's "usually 10+ opportunities" claim (`Landing.jsx:96`, repeated as a
  headline stat) contradicts §1's explicit design — "a run that surfaces six opportunities...
  is a good run" — and the onboarding tutorial's own copy ("Six results... is a good week").
  A prospective sign-up who reads the landing page first may read a normal week as
  underperformance.

---

## 2. Auth (Firebase) — ✅ shipped

Google sign-in through Firebase, the ID token verified in `app/auth.py` against Google's
public keys, one dependency on the whole `/api` router, and an `ALLOWED_EMAILS` allow-list
the app refuses to start without.

Still missing, in rough priority order:

- **No roles.** Every allow-listed person can do everything: replace the org's API key,
  delete every funder, start runs that spend money. Fine for one org of two or three
  people who trust each other; not fine as a product.
- **The allow-list is an env var.** Adding a colleague means SSH + edit `.env` +
  `systemctl restart` — and that restart kills any run in progress (§6). It must move into
  the database, at which point self-serve onboarding (§4) becomes possible.
- **No audit trail beyond logs.** `runs.started_by` now records who pressed the button,
  but settings changes and funder deletions record only a log line, and logs are not
  retained anywhere off-box.
- **No departure story.** Removing someone from `ALLOWED_EMAILS` stops future sign-ins;
  their existing ID token stays valid for up to an hour, and nothing revokes it.

---

## 3. Tenant isolation — ✅ shipped

**This was the most serious defect in the hosted app**, and it is fixed. Recording what it
was, because the shape of the bug is instructive: none of it was sloppiness, all of it was
a single-tenant design meeting a multi-user deployment.

Before: one SQLite file with no `org_id` column anywhere, and one `settings` row holding
one encrypted Anthropic key. Every signed-in person shared one dashboard.

| What went wrong | Why it was worse than it looks |
|---|---|
| **One API key row** | The second org to paste a key silently destroyed the first org's. Any signed-in person could delete a key they did not own. |
| **Environment-key fallback** | An org that had never pasted a key fell through to `ANTHROPIC_API_KEY` from the VM's `.env` — the deployer's own key. A brand-new account ran, looked like it worked, and billed somebody else. |
| **Shared findings** | `opportunities.id` is `stable_id(source_url, title)` — *derived*, not random. Two orgs looking at the same grant computed the same id, so the second write overwrote the first, taking its score and rationale. |
| **Shared dedup** | The second org to run in a month inherited the first's "already seen" set, so grants were dropped in the free tier — never fetched, never scored, never shown, with nothing in the log to explain the thin result. |
| **Shared purge** | `purge_old_months` ran before anything else in every run. Any org pressing Re-run on the 1st of a month wiped **every** org's archive first. |
| **Shared remove list** | CLAUDE.md calls it "the single exclusion lever, and it is the user's". It was everybody's: unticking a funder deleted it from every other nonprofit's search. |
| **Shared program cards** | A program card is the closest thing a small nonprofit has to written strategy. An unscoped `list_programs(active_only=True)` sent every org's into one system prompt, on whichever key happened to be stored. |

**What shipped.** Schema v7: `orgs` and `users` tables; `org_id` on `settings`,
`programs`, `funders`, `opportunities`, `runs`. The four tables whose identity is derived
from content are keyed on `(org_id, id)`, not `id` — that composite key is what stops one
org's row overwriting another's. Every query in `app/repo.py`, `app/archive.py`,
`app/secrets.py`, `agent/sources.py` and `agent/config.py` carries an org predicate, and
`org_id` is a **required keyword argument** rather than a defaulted one, so a missed call
site is a `TypeError` at import time instead of a silent cross-tenant read.

The org is resolved from the verified token by `current_org` in `app/main.py` and from
nowhere else — no query parameter, no body field, no header can select a tenant
(`tests/test_auth.py::test_the_org_cannot_be_chosen_by_the_caller`).

The migration moves every pre-existing row to `DEFAULT_ORG_ID`, so the pilot org keeps its
funders, cards, findings and saved key. The first person to sign in adopts that org;
everyone after gets their own.

Also fixed alongside it:

- **`run.json` was one deploy away from being public.** `sinks/webjson.py` wrote findings
  to `dashboard/public/run.json`. Vite copies `public/` verbatim into `dist/`, which
  `app/main.py` serves to anyone through the SPA catch-all — so the documented update
  procedure (`git pull && npm run build && systemctl restart`) would have published every
  org's grant pipeline at `https://<host>/run.json`. Harmless on 127.0.0.1; not harmless
  now. The sink is now opt-in (`--sink web`) and defaults outside any served directory.
- **Zombie run rows.** A restart left rows at `status='running'` for ever, so the
  dashboard showed a spinner for a search that died days ago. `reconcile_interrupted_runs`
  now runs at boot.
- **The Stop button had no owner check.** Any signed-in person could SIGTERM another
  org's five-minute run and destroy the money already spent on it.
- **Seed resurrection.** `init_db(seed=True)` re-ran the seeders on every process start
  and every pipeline run, so deleting a funder that meant nothing to your org lasted until
  the next restart — then all 44 came back, re-activated. Seeding is now first-boot-only,
  marked in `meta`.

### Since shipped

- **Colleague invites.** An admin generates a single-use code (`POST /api/org/invites`)
  and shares it however they already talk to their team; the joiner redeems it
  (`POST /api/org/join`) and lands in that org with its funders, cards and findings.
  Deliberately a code rather than an emailed link — sending mail needs a provider, a
  domain reputation and a bounce story, and CLAUDE.md rules out the app sending mail on
  anyone's behalf.
- **A new org starts clean.** Signing up no longer hands a Chicago nonprofit 44 San Diego
  funders and seven program cards belonging to the pilot; new orgs get working settings
  and an empty funder list.
- **Concurrent runs across orgs**, one per org — see §9.
- **A per-org monthly spend cap** (`monthly_budget_usd`) that refuses a run once the
  month's ceiling is reached, and trims the month's last run to the remaining headroom
  rather than overshooting it.

### What tenancy still does **not** give you

- **No roles.** Anyone in an org can invite a colleague, replace the API key, and delete
  every funder. Fine for a nonprofit of three who trust each other; not fine as a product.
- **No frontend for any of it.** The invite, member-list and spend endpoints exist and
  have tests; nothing in `dashboard/src/` calls them yet, and there is no onboarding
  walkthrough for a new org (§4).
- **No org names.** `orgs.name` exists and nothing sets it.
- **The org switcher is still a stub** (`dashboard/src/components/OrgSwitcher.jsx`). It
  renders a chevron and an "+ Add an organization" button that do nothing, which now
  actively misleads: it implies switching is possible.
- **Per-org config is still partly pilot seed.** The geography filter now reads
  `org_location` (see below), but the *scoring prompts* still carry San Diego language.
  Either wire that up or
  remove the field; a setting that lies is worse than a missing one.

---

## 4a. ⭐ The funder directory — the next real feature

Today the funder list is **44 grantmakers in San Diego that we researched by hand and
hardcoded** (`agent/sd_funders.py`). That does not scale past the pilot: a Chicago
nonprofit signs up, gets an empty list, and has to know the names of their own local
foundations before the product does anything for them. Hand-researching a second city
does not fix it either — it just moves the cliff.

**The page exists** — *Discover funders*, above Settings in the sidebar. It holds the
starter lists and the funder list itself, and a disabled card describing the part below.
What follows is what that card is a placeholder for.

**By city.** Today there is one city, so the lists are flat. A directory of grantmakers
**by city** Not this week's opportunities — the standing list of who gives
money where. An org browses it, picks the cities they can apply in, and those funders
feed the weekly search. Selecting cities on the dashboard replaces every notion of a
geographic filter (see the note at the top of `agent/filters.py` for why the old one is
gone rather than fixed).

**Finding more.** A button that sends a *stronger* model — Opus, not the Haiku/Sonnet
tiering the weekly run uses — out to look for grantmakers in a city that are not in the
list yet. It runs **on the org's own API key**, like everything else, so the cost lands
where the value does. This is a different job from the weekly crawl and should not be
squeezed into `agent/run.py`: the weekly run scores *opportunities* against an award
floor; this discovers *organizations* and has to verify they exist, give money, and are
in the right place.

Non-obvious parts, roughly in the order they will bite:

- **The accuracy gate applies here too.** A hallucinated foundation is worse than a
  missing one — it sends a nonprofit chasing an organization that does not exist. Every
  entry needs a URL that was fetched and a verbatim quote, exactly as `agent/verify.py`
  demands of an award amount. "Found by AI, unverified" is a state the UI has to show.
- **Cost.** Opus over an open-ended search is not a $1 run. It needs its own ceiling,
  its own confirmation step, and an honest estimate before the user presses the button.
- **Deduplication against the existing list**, which is a name-matching problem
  ("The Parker Foundation" vs "Parker Foundation") the funder table does not solve today.
- **Where results land.** Probably a per-org candidate list the org promotes into their
  own funder list, rather than writing directly into it — a discovery run that silently
  adds 30 funders to next week's crawl is a surprise bill.
- **`agent/discovery.py` already exists** as a seam with a null provider. This is what
  goes in it.

### Stretch: a shared directory

If a Chicago nonprofit pays Opus to find and verify the grantmakers in Chicago, every
other Chicago nonprofit on the platform should be able to download that list instead of
paying to rediscover the same twenty foundations. That is the network effect this product
has available to it, and it inverts the economics: the first org in a city pays, everyone
after inherits.

Not a small feature, and worth writing down what it drags in:

- **Publishing is a decision, not a default.** A funder list is not sensitive the way
  findings are, but an org should opt in per city, not have their research taken.
- **Trust and provenance.** A shared entry needs to say who verified it and when, and
  a stale directory is worse than none — foundations close, programs end, URLs rot.
- **Moderation.** Anything user-contributed and publicly visible needs an answer for
  spam and for a wrong entry that costs someone a week.
- **It is the first thing in this product that crosses tenant boundaries on purpose.**
  Everything in §3 exists to keep orgs apart; this deliberately shares one narrow slice,
  and the mechanism should make that narrowness structural rather than a promise.

---

## 4. Onboarding — the BYO-key cliff

BYO-key's cost is friction: the user has no AI experience, and "go to console.anthropic
.com, add a card, create a key, paste it" is the steepest step in the whole product. The
money is small (~$2–6/org/month); the *setup* is the barrier.

Now that a new org gets no key by default (§3), this is on the critical path rather than
a nicety: a new sign-in currently lands on a dashboard seeded with 44 San Diego funders
and seven program cards that are not theirs, and nothing scores until they paste a key.

- A **guided onboarding walkthrough**, including a screenshot-by-screenshot "how to get
  your Anthropic API key" guide.
- **Validate the key the moment it's pasted.** `POST /api/settings/api-key/test` already
  exists (one token, effectively free) — surface it in onboarding.
- **Do not seed a new org with the pilot's data.** Ask for their region and programs
  instead.
- Keep the door open for a **shared trial key** with a tight per-org weekly cap, so an org
  sees value before setting up billing.

---

## 5. Security and abuse — open

Found during the post-deployment audit. Roughly in priority order.

1. **SSRF in the fetcher** — ✅ **fixed**. `app/assistant.py` validated only that the URL
   started `http://` or `https://`, `agent/fetch.py` set `follow_redirects=True`, and
   nothing anywhere looked at where a hostname actually pointed. Any signed-in user could
   aim the server at `127.0.0.1:8000` (Fundworthy itself, from inside nginx) or
   `169.254.169.254` (cloud instance metadata, which answers unauthenticated) and read the
   response back out of the assistant's draft card.

   `agent/urlguard.py` now resolves every hostname and refuses any that answers with a
   loopback, private, link-local, reserved, multicast or CGNAT address — including
   IPv4-mapped IPv6 forms like `::ffff:127.0.0.1`, whose `.is_loopback` is `False`. The
   check runs **per redirect hop**, which meant taking redirect-following away from httpx
   and doing it in `Fetcher._send`: the redirect was the part we never inspected, so a
   perfectly ordinary public URL could bounce us into the metadata service.

   **Residual risk, deliberately left:** the guard resolves a name and httpx then resolves
   it again to connect. A name answering public-then-private across those two lookups —
   DNS rebinding — still gets through. Closing it means pinning the connection to the
   validated address via a custom transport. Every direct attempt and every redirect chain
   is blocked, which is the whole of the realistic risk; this is written down rather than
   papered over.

2. **Rate limiting** — partly done. A per-org **monthly** cap now exists
   (`monthly_budget_usd`, enforced in `RunManager.start`), which was the severe half:
   before per-org keys, repeated Re-run clicks drained *somebody else's* credit. Now an
   org can only overspend its own, and only up to its own ceiling.

   Still open: no per-minute rate limit on `POST /api/runs` or `POST /api/programs/draft`,
   so a script can still hammer the box (not the budget). And each org should be told
   during onboarding to set a spend limit in **their own** Anthropic console — that is
   the only ceiling that survives a bug in ours.

   Worth knowing, since it comes up every time: **Anthropic publishes no credit-balance
   endpoint or header.** The `anthropic-ratelimit-tokens-remaining` header is tokens per
   minute and refills; it is not dollars. So "show the org how much credit is left" is
   not buildable — `repo.spend_summary` shows what *we* spent instead, which is the
   number they can hold us to.
3. **No request-size limits or nginx rate limiting.** No `client_max_body_size`, no limit
   zone, and `proxy_read_timeout 900s` is a cheap way to tie up workers.
4. **Secrets on the box.** `data/.fernet-key` sits next to `data/rise.db`, and it now
   guards *every* org's key rather than one. Anyone with read access to `data/` has both.
5. **Security headers** — ✅ done in the app (`app/main.py` middleware: CSP,
   `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`).
   **HSTS is deliberately not there** — it belongs on nginx, because setting it from the
   app would also send it to a local `http://127.0.0.1:8000` install and pin that
   hostname to HTTPS in a developer's browser for a year. Add it to the nginx server
   block on the VM.
6. **npm audit reports 2 vulnerabilities** (1 moderate, 1 high) as of the Firebase merge.
   Not yet triaged; `audit fix --force` is a breaking change so it needs a real look.

---

## 6. Push-to-deploy — ✅ shipped

`.github/workflows/deploy.yml` runs the suite on GitHub, then SSHes in and runs
`scripts/deploy.sh` on the VM. Tests first, on a machine where failing is free: a
pipeline that deploys and then tests tells you about the migration bug after it has run
against a nonprofit's only copy of their data.

The careful part is on the VM, because deciding whether it is safe to deploy needs the
database. `scripts/deploy.sh`:

1. **Touches a drain file**, so new searches are refused while the deploy runs.
2. **Waits** for in-flight runs to finish, polling `runs WHERE status='running'` — up to
   15 minutes, then aborts and changes nothing. It reads the DB rather than asking the
   API, because a public "is anything running" endpoint would be an unauthenticated fact
   about usage, and the API is about to restart anyway.
3. **Backs up** `rise.db` (via `.backup`, not `cp` — WAL keeps writes in a side file, so
   copying the main file can capture a torn database) **and** `.fernet-key`, without
   which every stored API key is permanently unrecoverable.
4. Pulls, installs, **runs the suite again on the VM**, and rolls the code back if it
   fails rather than restarting the service.
5. Restarts and health-checks; the drain file is removed by an `EXIT` trap whatever
   happens, so an aborted deploy cannot leave the app permanently "being updated".

And the pipeline now **survives being interrupted**: `agent/run.py` catches SIGTERM and
raises `RunInterrupted`, an ordinary `Exception`, so it lands in the salvage block that
already existed. Previously Python's default handling killed the process where it stood —
the salvage never ran, and every scored opportunity plus the credit spent on it was lost.

`.github/workflows/weekly.yml` is deleted. It read config from a Google Sheet the
dashboard cannot write to and had never been switched on.

### Still open

- **No incremental persistence.** Results reach the sinks once `evaluate()` finishes, so
  the salvage path is what saves an interrupted run rather than a running write. Good
  enough now that SIGTERM is handled; worth doing when runs get longer.
- ~~**The weekly schedule still does not exist.**~~ **Shipped** — `app/scheduler.py`, a
  background thread in the API process rather than a systemd timer, so it shares
  `RunManager`'s concurrency cap, the drain gate, and per-org keys. A timer calling
  `python -m agent.run` would have bypassed all three, and the first thing it would do
  wrong is start a run during a deploy. Each org picks its own day, hour and timezone.

  What it inherits from `RunManager`: scheduling stops if the process is down, and a
  second uvicorn worker would double-fire. Both are fixed by the same job queue.
- ~~**Protect `main`** on GitHub: require a PR, no force-push.~~ **Done**, and confirmed
  the way you would want to confirm it: a direct `git push origin main` was refused by the
  remote — *"Changes must be made through a pull request. Required status check `test` is
  expected."* So the `test` job in `.github/workflows/deploy.yml` is a real gate rather
  than a convention, and every change reaches the VM through a PR. Noted here because the
  §6b design notes below still list it as outstanding.

---

## 6b. The original design notes (kept for reference)

**The goal:** merge to `main` → the VM pulls, rebuilds, restarts → production is current,
with no one SSHing anywhere.

**The constraint, and it is a real one:** a deploy must never interrupt a customer's
in-flight search. This is not caution — it is a measured, verified loss:

- `agent/run.py:689` runs `evaluate()`, and results reach the sinks only at `:743`, after
  the whole evaluation completes. **There is no incremental persistence and no
  checkpointing.**
- There is **no signal handling anywhere in the pipeline** (`grep -rn "signal\|SIGTERM"
  agent/ app/` finds only comments). SIGTERM kills the process outright; the
  `except Exception` at `agent/run.py:691`, which exists precisely to salvage partial
  results, never executes.
- The pipeline is a `subprocess.Popen` **child** of uvicorn, and the systemd unit sets no
  `KillMode`, so the default control-group kill takes the child down with the parent.

Net effect: `systemctl restart` at minute 7 of a 10-minute run destroys every scored
result **and** the ~$1 of the org's own Anthropic credit already spent on them, with
nothing written. For a nonprofit on a $2–6/month budget that is a real cost, caused by us,
for a change they did not ask for.

### The design

Four pieces. The first two are the deploy gate; the second two make interruption survivable
even when the gate is bypassed.

**a. Ask before restarting.** The Action already has an SSH session. Before touching
anything, have it query the database on the box and refuse to proceed while a run is live:

```bash
# on the VM, inside the deploy step
running=$(sqlite3 ~/Rise-Fund-Finder/data/rise.db \
          "SELECT COUNT(*) FROM runs WHERE status='running';")
```

Wait-and-retry with a ceiling (a run is capped at ~10 minutes), then either proceed or
fail the job so a human decides. Deliberately reading the DB rather than adding a public
"is anything running" endpoint — that would be an unauthenticated fact about usage.

**b. A drain flag.** A file (or a `meta` row) the API checks in `POST /api/runs`, so that
during a deploy new runs are refused with an honest message ("an update is being
installed, try again in a few minutes") rather than started and then killed.

**c. Make an interrupted run cost less.** Two independent changes, both worth doing on
their own merits:
   - **Persist incrementally.** Write each scored opportunity as it is produced rather
     than batching to the end. The sink is already an upsert, so this is mostly moving the
     call.
   - **Handle SIGTERM.** A handler that lets the existing salvage path at
     `agent/run.py:691` run, plus `KillMode=mixed` and a `TimeoutStopSec` longer than the
     salvage takes, so systemd asks before it insists.

**d. Reconcile on boot** — ✅ already shipped (§3), and it is the backstop for every case
above: whatever else happens, no run is left showing a spinner for ever.

### Also needed for the pipeline itself

- ~~**Protect `main`** on GitHub: PR required, no direct pushes, no force-push.~~ **Done**
  — see §6 above; the remote refuses a direct push and requires the `test` check.
- **Run the test suite in the Action before deploying.** The suite is offline and takes
  ~3 seconds; there is no excuse for it not gating a deploy.
- **Deploy key, not a password.** A dedicated SSH key in GitHub Secrets, with its public
  half in the VM's `authorized_keys`.
- **Back up before migrating.** `git pull` can carry a schema migration. Copy
  `data/rise.db` and `data/.fernet-key` off-box first, every time — see §7.
- **Retire `.github/workflows/weekly.yml`.** It reads config from a Google Sheet that the
  dashboard cannot write to, and has never been switched on. Weekly runs belong on the VM
  as a systemd timer. Note the trap when that lands: a scheduled run reads the
  environment directly, so under BYO-key it must resolve **each org's** key from the
  database and run per-org, not once globally.

---

## 7. Operations — open

- **Backups are a bullet point in a doc, not a cron job.** If the VM dies today, the org's
  settings, funders, findings and encrypted key go with it. Losing `data/.fernet-key`
  makes every stored API key permanently unrecoverable. Automate a nightly copy off-box.
- **Nothing tells anyone the service is down.** No uptime check, no error alerting. Two
  people with day jobs will find out from a user.
- **Oracle idle reclamation.** Always-Free compute that looks idle over a 7-day window can
  be reclaimed. A once-a-week app is a candidate. Mitigate with a periodic health ping or
  upgrade to Pay-As-You-Go (keeps the free resources, exempts them from reclamation).
- **Certbot renewal fails silently.** Nothing checks it until the site stops loading.
- **DuckDNS is a single free subdomain.** If the VM's public IP changes the site goes
  down *and* certificate renewal fails with it.
- **Disk.** SQLite WAL, journald, and npm caches on a free-tier box with no swap.

---

## 8. Access and bus factor — do this first

Not code, and more urgent than any of it. Five separate accounts control the running
service — SSH, Oracle Cloud console, Firebase, DuckDNS, Anthropic — and at the time of
writing they are held by one person. Nobody else can restart the service, renew the
certificate, add a user, or rotate the API key if a key leaks.

The runbook is [docs/ACCESS.md](docs/ACCESS.md), including the message to send. Until it
is done, every item in this file has a single point of failure in front of it.

---

## 9. Scale — why the VM is not the bottleneck (reference)

When "will it handle 1000 users?" comes up: the free Oracle ARM box is a capable machine.
The order in which things actually break — the VM's raw compute is never near the top:

1. **Anthropic API cost** — solved by BYO-key, now genuinely per-org (§3).
2. **Anthropic rate limits** — per-tenant under BYO-key.
3. **The run manager.** `MANAGER` in `app/runner.py` now allows one run **per org**, up
   to `FUNDWORTHY_MAX_CONCURRENT_RUNS` (default 3) at once. The old global lock was
   correct while there was one shared key and therefore one shared budget; per-org keys
   removed that reason, and making one nonprofit wait a week for another's crawl was
   costing the product its whole point. What remains is the part that was always
   per-org: a second run for the *same* org would double-spend that org's budget.

   Still in-process, so it is still the load-bearing change: run state and logs live in
   this process's memory, which means you cannot add uvicorn workers (each gets its own
   `MANAGER`, and `/api/runs/current` only sees its own worker's runs). A real queue
   (Arq/RQ/Celery) plus run state in the database is the fix.
4. **Polite-crawler collisions.** N orgs crawling the same ~50 funder sites every week is
   N hits from one server IP in a burst, which the per-host politeness in `agent/fetch.py`
   cannot prevent *across* tenants. A shared URL+week fetch cache fixes it — not for cost
   (each org pays its own) but so we do not become a nuisance to the funders.
5. **SQLite write concurrency** — needs Postgres. The store uses raw `sqlite3` with
   SQLite-only pragmas (WAL, `busy_timeout`) and `ON CONFLICT` patterns, so it is a real
   port of `app/db.py` + `app/repo.py`. Use the provider's connection pooler.

Near-term reality is dozens of orgs, not 1000 concurrent. A single free VM handles that
with room to spare; the fix if it is ever outgrown is a second free VM as a worker, not a
rewrite.

---

## 9b. Page speed and accessibility — open

Measured 5 Aug 2026 against the live site with Lighthouse 12, the engine PageSpeed
Insights runs. PageSpeed itself could not be read directly — its report page is a
JavaScript shell with no data in the HTML, and the public API was out of daily quota — so
these are local runs against `https://fundworthy.duckdns.org`, and every server-side
finding below was re-checked by hand with `curl` rather than taken from the audit label.

| | mobile | desktop |
|---|---|---|
| Performance | **57** | 91 |
| Accessibility | 93 | 93 |
| Best practices | 100 | 100 |
| SEO | 100 | 100 |
| Largest Contentful Paint | 9.0 s | 1.5 s |
| First Contentful Paint | 8.4 s | 1.3 s |
| Total Blocking Time | 0 ms | 0 ms |
| Cumulative Layout Shift | 0.002 | 0.001 |

The gap between 57 and 91 is not the app. Blocking time is zero and layout shift is
nil — the JavaScript is not the problem and neither is the design. Mobile is scored on a
throttled connection, and on a slow connection **what we ship uncompressed is what hurts**.
Three nginx settings account for most of it, and none of them require touching the code.

**1. gzip covers HTML but not JavaScript or CSS.** The biggest single win.

```bash
curl -H "Accept-Encoding: gzip" -I https://fundworthy.duckdns.org/assets/index-Cg-fzf0Y.js
# no Content-Encoding; 218,769 bytes on the wire
curl -H "Accept-Encoding: gzip" -I https://fundworthy.duckdns.org/
# Content-Encoding: gzip
```

nginx's default `gzip_types` is `text/html` and nothing else, so the HTML compresses and
the 490 KB of JavaScript and CSS behind it does not. Est. **357 KiB / ~2.6 s** on mobile.
Add to the server block:

```nginx
gzip on;
gzip_min_length 1024;
gzip_types application/javascript text/css application/json image/svg+xml application/xml;
gzip_vary on;
```

**2. Hashed assets are served with no `Cache-Control` at all** (`cacheLifetimeMs=0` on
every one). Vite already puts a content hash in each filename — `index-Cg-fzf0Y.js`
changes name whenever its contents change — so they are safe to cache for a year, and a
returning visitor currently re-downloads all of it. Est. **565 KiB**.

```nginx
location /assets/ { add_header Cache-Control "public, max-age=31536000, immutable"; }
```

Do **not** extend this to `index.html`, `robots.txt` or `sitemap.xml`. Those keep their
names across deploys, and caching them for a year is how a deploy stops being visible.

**3. HTTP/1.1 only.** `curl --http2` still negotiates 1.1, so the eight asset requests
queue instead of multiplexing. Est. **~370 ms** on mobile. nginx 1.18 wants it on the
listen directive (`http2 on;` is 1.25.1+):

```nginx
listen 443 ssl http2;
```

Then the code-side items, in descending order of payoff:

- **222 KiB of unused JavaScript**, most of it Firebase, on a landing page that needs none
  of it. `dashboard/src/auth.js` imports Firebase dynamically so a local install never
  loads it — but on the deployed site sign-in *is* on, so it loads eagerly for a visitor
  who is only reading the page. Defer it until the person clicks **Sign in** or **Create
  an account**.
- **Render-blocking CSS: 2,280 ms on mobile**, of which the Google Fonts stylesheet is
  855 ms — a blocking request to a third-party host before anything paints. Self-host
  Albert Sans, or at minimum `preconnect` and set `font-display: swap`.
- **83 KiB of unminified JavaScript**, both chunks Firebase ESM builds (`index.esm-*.js`).
  Worth a look at why Vite is passing them through unminified; it may be a one-line
  config change.
- **The LCP element is `p.lp-lede`** — the hero paragraph, plain text with no image
  behind it. It takes 9 s on mobile only because it waits on the CSS above. Fix the
  blocking chain and the LCP number follows; there is nothing to optimise in the element
  itself. TTFB is 609 ms, 7% of the total — the server is not the problem.

**Accessibility — 15 nodes fail colour contrast, and almost all are one token.**
`--muted: #8A8578` in `dashboard/src/styles.css:27` gives 3.68:1 on white, 3.38:1 on
`#f7f5f1` and 3.20:1 on `#f1efea`. WCAG AA wants **4.5:1** for text this size. It is used
in ~40 places, so this is one line for most of the fix:

| | on `#fff` | on `#f7f5f1` | on `#f1efea` |
|---|---|---|---|
| `#8A8578` (today) | 3.68 | 3.38 | 3.20 |
| `#6E6A5C` | 5.41 | 4.97 | 4.71 |

`#6E6A5C` is about the lightest value that clears 4.5:1 on all three backgrounds, so it
passes without flattening the palette. Separately, `.lp-step` uses `#a06b4f` at 4.46:1 —
failing by four hundredths — and `#9C6749` (4.72) fixes it.

This matters more than a score: the users are nonprofit administrators, a population
skewing older, reading 12.5–13.5 px grey text. It is also the one item here with a legal
dimension, since a nonprofit's own funders may ask about WCAG conformance.

**What not to bother with.** Mobile 57 looks alarming next to desktop 91 and is mostly an
artefact of Lighthouse's simulated slow connection. Fix the three nginx settings and the
same measurement improves without a line of application code changing. There is no
evidence any real user is experiencing this — the Chrome UX Report has no field data for
the site, which is simply what "not enough visitors yet" looks like.

---

## 10. Still-open product questions

- Can the org meet a 1:1 **match requirement**? Currently flagged, not filtered.
- The **calibration fixtures** in `tests/calibration.py` are not the pilot's own — a pass
  proves the pipeline ranks, not that it is calibrated to a real reviewer's judgement.
- **Beyond-partners discovery** (`agent/discovery.py`) is a seam with a null provider.
- **Nothing tells a user what a run cost them**, before or after.
- **No privacy policy, terms, or data-retention statement**, and no way for an org to
  delete its data. We now hold other organisations' information on a US cloud VM.
