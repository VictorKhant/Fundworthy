# CLAUDE.md — Fundworthy

The working spec for this repo. Read it before writing any code. It describes **what
Fundworthy is and how it works today** — not history, not roadmap. The roadmap
(multi-tenant, accounts, hosting-at-scale) lives in [FUTURE.md](FUTURE.md).

---

## 1. What it is

Fundworthy is a **funding-opportunity agent for nonprofits**. Once a week it reads the
funders a nonprofit cares about, and leaves a short, sourced, ranked list of what is
actually worth applying for.

**The problem it solves is not "find more grants."** A nonprofit's staff can already
find grants; the problem is that most of what they find is too small to justify the
hours an application takes. So Fundworthy is deliberately built to return **few**
results — every one above an award floor — and to say *"amount not stated"* rather than
guess. A run that surfaces six opportunities, all above the floor, is a good run. A low
count is not a failure.

The whole cost strategy is tiered so that a weekly run costs about **$1** and stops
itself before it can cost more.

### The user, and the one hard rule

The user is a nonprofit administrator with **no AI experience**. That is the binding
design constraint:

- **The user never writes a prompt.** Any workflow that requires phrasing a request to
  an AI is wrong. Where the agent needs program context, the user *pastes a link* and
  reviews a draft (see `app/assistant.py`) — they correct a draft, never compose an
  instruction.
- The user's surface is a **web dashboard**: read a list, tick boxes, edit a card, paste
  an API key. No terminal, no config file, no repo.

---

## 2. Status — what is built, what is stubbed

**Built and working, end to end:**

- FastAPI backend + React dashboard, run with one command (`./start.sh`).
- SQLite store for all config and results (settings, programs, funders, findings, runs).
- The pipeline: fetch → parse → free deterministic filters → Haiku triage → Sonnet
  scoring, behind a hard per-run budget ceiling.
- The accuracy gate (`agent/verify.py`): a sourced value is nulled unless the model
  returns the verbatim sentence it came from and that sentence is on the fetched page. The
  other half of "no URL, no record" — `Opportunity.__post_init__` (`agent/models.py`)
  refusing to construct a record with no usable `source_url` — is enforced in code the same
  way it always was; `tests/test_accuracy_gate.py` now actually constructs a bad one and
  checks it's rejected, rather than only exercising the quote-matching helpers around it.
- Dashboard controls: award floor, deadline runway, result cap, spend limit, hours per
  application, program cards as a chip row in a **"What to search for"** panel at the top
  of This week, an editable funder list with search and paging, a monthly archive, a
  Re-run button, a real Stop.
- **Light and dark** (`body[data-fw-theme]`, a control at the foot of the sidebar). The
  dark palette is derived from the light one — same hues, moved down — because the
  previous attempt was cool grey against a warm light theme and was dropped for it.
  Default is light and `prefers-color-scheme` is deliberately not consulted.
- **Three stage boxes** (`components/Stages.jsx`) in place of the streaming log as the
  primary account of a run: free filters → Haiku triage → Sonnet scoring, each showing
  the pass count alone at display size with the denominator in its footer. Opening one
  lists **which** pages were set aside and why, with the specific fact — "$4,000 <
  $10,000", or triage's own fifteen words — and, above that, the rule that let the rest
  through. The log is kept verbatim behind "Show the technical log" in the section
  header, because it is still the only thing that explains a run that died halfway.
- **The boxes are the run while it happens.** They were hidden for the whole of a search
  and appeared at the end holding finished numbers, which made the one thing somebody
  watches for ten minutes the one thing they could not see. The working box lifts and
  pulses, the ones behind it dim, and each carries a progress rail. Those rails divide by
  real totals or say they cannot: stage 2 is "of the pages that survived the free
  filters, how many have been read" and stage 3 is "of the results you asked for, how
  many are found" (the `target_met` condition), while stage 1 **sweeps** rather than
  filling — nothing knows how many pages a funder list will yield until it has been
  fetched, and a bar filling against an invented total is the one dishonest pixel this
  page could have had.
- **A box and its own breakdown count the same population.** Stage 1 reads "came in" from
  `candidates_parsed` and "set aside" from came-minus-through, while the reasons
  underneath come from `rejected_by_filter` — and rejects made *inside* an API adapter
  (`agent/apis.py`: off-mission category, not open to nonprofits, loan-not-grant) went
  into the second counter and not the first. A real run showed **"47 set aside" above a
  list whose first two rows already summed past 118**. Both numbers were right about
  different populations, which is the one way a panel built to explain a thin week can
  make it less explicable. A record an adapter refused was a candidate considered and
  declined for free, exactly like a page that fails `apply_filters`, so `crawl()` now
  counts it in both. The last gap was intra-run duplicates: `consider()` counted the page
  and returned early without naming a reason, so a grant two funders both link raised
  "came in" and nothing else. It records `already_seen_this_run` now — distinct from
  `already_seen_this_month`, which is the monthly archive dedup. **The invariant is
  `candidates_parsed − survivors == sum(rejected_by_filter)`**, asserted directly by
  `tests/test_pipeline_reporting.py::test_stage_one_adds_up_exactly` so the next exit path
  that forgets to name its reason fails a test rather than a nonprofit's screen.
- **"Worth paying to read" is its own persisted number, not `triaged`** (`runs.survivors`,
  schema v16). They are the same only on a run that read everything: `survivors` is what
  the free filters passed, `triaged` is how many of those we then got round to. It used to
  live only in the live `progress` JSON — on the reasoning that it was "meaningless the
  moment the run ends", which was exactly backwards — so a finished run fell back to
  `triaged`. Harmless while every run read its whole list, and badly wrong the moment one
  stopped early: a run the consecutive-error breaker halted after 5 failures reported
  **"5 went through" of 344** when the free filters had actually passed 157. Written live
  *and* by the sink, so the boxes read the same field during a run and after it.
- **The technical log outlives the run** (`runs.log_tail`, v16, last 200 lines). It was a
  `deque` on `RunManager`'s in-process slot, deleted in the same `finally` block that reaps
  the child — so for every finished run, which is every run somebody wants to read a log
  for, "Show the technical log" opened onto nothing. `_persist_log` writes it before the
  slot is dropped; `GET /api/runs/current` serves the live buffer while running and the
  stored tail afterwards. Deliberately **not** on `/api/state` — hundreds of lines on every
  dashboard load for something almost nobody opens — so the dashboard fetches it on demand
  when the disclosure is opened, the same way stage boxes fetch rejects.
- **A tier that fails says so in the same place a tier that rejects says so.** A
  `triage()` or `score_one()` call that raised was counted in a local `scoring_errors`,
  written to the log, and summarised once in `run.notes` — none of which any dashboard
  component rendered. So a search whose every model call failed on an expired key showed
  *"164 came in, 0 went through, $0.0000 spent"* above the words **"Nothing was set aside
  at this step"**: the pipeline knew exactly what was wrong 164 times and had nowhere to
  put it. The exception is now a reject row like any other — `triage_error` at stage 2 or
  `scoring_error` at stage 3, recorded against whichever tier was actually running, with
  the exception text in the same slot that holds "$4,000 < $10,000".
- **A systemic failure stops the run** (`agent/run.py: CONSECUTIVE_ERROR_LIMIT`, five).
  A bad key or a bad model id fails identically on every candidate, and the loop used to
  work through all of them one API error at a time — spending minutes to learn what the
  fifth attempt already knew, then ending as `sources_exhausted`, which reads as a quiet
  week. Five *consecutive* failures (a single odd page must never abort a search) ends the
  run as `error` with a note that says it is not a quiet week.
- **The run's own notes are on the page** (`pages/Dashboard.jsx`, under the outcome line).
  `run.notes` is where the pipeline writes what it wants a person to know — a ticked
  program that matched no California funding category and therefore searched nothing, a
  budget ceiling, a tier that could not read anything. It reached `/api/state` as
  `latest_run.notes` and stopped there, unrendered. Two purely-bookkeeping shapes are
  filtered out and **an unrecognised note is shown**: a new note nobody thought to
  whitelist should look noisy rather than be swallowed, which is the same direction to
  fail in as `StageDetail`'s label fallback.
- **Which model runs each paid step** is a setting, chosen from the Engine row under
  those boxes, with the projected cost on each option (`triage_model` / `scoring_model`,
  stored as `provider:model`). **Which provider** those models come from is a panel on
  Settings ("Which AI it uses") — Anthropic live, OpenAI/DeepSeek/Qwen present and
  visibly disabled, because connecting one needs a provider column on the stored key, an
  adapter interface in `agent/score.py` and per-provider pricing, and none of that is
  built. A card that names the thing is a signpost; leaving them out would make the model
  picker's "add a provider" line point at nothing.
- **How hard the chosen model thinks is a second, separate dial** in the same picker
  (`triage_effort` / `scoring_effort`, Anthropic's `output_config.effort` — Default /
  Low / Medium / High / Max), because a stage's cost and quality depend on both *which*
  model runs it and *how much it reasons before answering*, and conflating the two into
  one control would hide the second axis entirely. **Haiku cannot take an effort level
  at all** — sending one is a live 400, not a preference — and this was a real, shipping
  bug independent of the new setting: `score_one()` sent `thinking={"type": "adaptive"}`
  unconditionally, so picking Haiku as the *scoring* model, a real choice
  `MODEL_CHOICES[3]` has always offered, made every scoring call in the run fail and the
  run abort once `CONSECUTIVE_ERROR_LIMIT` was reached — with no relation to whether
  anyone had ever touched an effort setting. `agent/score.py: _model_supports_effort`
  gates both `triage()` and `score_one()` now, and the picker explains the gap on Haiku
  ("does not support a reasoning-depth setting") rather than rendering controls that
  would break the next search.
- **Ultra mode** (`ultra_mode`, off by default, "Adjust search settings" on This week):
  spend the whole search budget instead of stopping at "most results to bring back".
  CLAUDE.md's whole premise is that a short list is a feature, not a shortfall, so the
  cap is the norm and this is the one switch that deliberately abandons it for someone
  who has decided otherwise. It changes exactly one thing in `evaluate()`: the
  `len(out) >= cfg.max_opportunities` check (and balanced mode's per-kind cap) never
  fires, so `StopReason.TARGET_MET` can no longer end the run — only `BUDGET` (a real
  `BudgetExceeded`) or `SOURCES_EXHAUSTED` (the ranked candidate list itself running
  out) can. It does not reach further than the funder list already does: a 20-funder
  list still tops out at 20 candidates regardless of the setting, and the run's own
  notes say so when it is on.
- Spend **moves while a search runs**, with a LIVE marker beside it — an unlabelled
  number changing by itself reads as a glitch. It used to be written only at the end.
- One themed confirm dialog (`components/Confirm.jsx`) instead of `window.confirm` —
  every destructive path says what will happen rather than asking "are you sure?".
- **Responsive on two breakpoints and only two**, 900 and 620. Below 900 the sidebar
  stops holding a column open and anything in two or more columns drops to one; below
  620 every tap target reaches 44px. Wide content scrolls inside its own container and
  the page body never scrolls sideways.
- Settings page storing the Anthropic API key **encrypted at rest, write-only** (no
  endpoint ever returns it).
- CSV export of the week's findings, named after the org that downloaded it — it was
  `rise-funding-…` for everybody, which put the pilot's name on another nonprofit's
  spreadsheet.
- A five-step first-run walkthrough (`dashboard/src/components/Tutorial.jsx`): key,
  program card, funder list, the weekly schedule (optional — skipping is a real answer),
  and what to expect. Which step it opens on is read from the account, so closing the tab
  resumes where you stopped; *whether it appears at all* is the stored `onboarding_done`
  flag, so finishing it once is final.
- **Accounts and roles**: an Admin badge on whoever created the org, member removal and
  ownership transfer for them alone, and account deletion for anybody. What leaving takes
  with it — and what it deliberately leaves behind — is under "Leaving one" below.
- **Search preflight** (`app/runner.py: preflight`): a search that could not have worked
  is refused with a sentence naming the one page that fixes it — see §5.
- **Sign-in** (`app/auth.py`): Google via Firebase Authentication, the ID token verified
  server-side, gated by an explicit allow-list. Off unless configured — see below.

**Single-tenant, and local unless you deploy it.** There are exactly two safe shapes, and
the app enforces both:

| | |
|---|---|
| **Local** (default) | Binds `127.0.0.1`, no sign-in. Nothing can reach it, so there is nobody to authenticate. `./start.sh` opens straight onto the dashboard. |
| **Deployed** | `FIREBASE_PROJECT_ID` set → every `/api/*` route requires a signed-in person. Add `ALLOWED_EMAILS` to restrict who; leave it out and any nonprofit may sign up. See [docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md) §8. |

Firebase authenticates *who* someone is and says nothing about whether they belong here,
so the second question is answered in `app/auth.py` — by `ALLOWED_EMAILS` if it is set,
and by nothing at all if it is not. **Open is the default**, because that is what this
product is: any nonprofit can sign up and use it.

That is safe in a way it would not have been before per-org keys: a new account gets its
**own org with no key**, so it cannot spend anyone's money. What it can still do is make
the server crawl on the free tier, which `FUNDWORTHY_MAX_RUNS_PER_DAY` can bound if one
account ever misbehaves.

**Multi-tenant storage** (schema v14). Every row has an owner. `orgs` and `users` tables;
`org_id` on `settings`, `programs`, `funders`, `opportunities` and `runs`; and each org
holds **its own encrypted Anthropic key**, so one nonprofit can never spend another's.

Two details worth knowing before touching the data layer:

- The tables whose ids are *derived from content* — `funders.id` is a hash of (name, url),
  `opportunities.id` is `stable_id(source_url, title)` — are keyed on **`(org_id, id)`**.
  Two orgs looking at the same grant compute the same id, so a bare `id PRIMARY KEY` let
  the second write silently overwrite the first.
- `org_id` is a **required keyword argument** on every function in `app/repo.py`,
  `app/archive.py` and `app/secrets.py`. That is deliberate: a default would make a
  forgotten call site a silent cross-tenant read instead of a `TypeError`.

The org comes from the verified ID token via `current_org` in `app/main.py` and from
nowhere else — no query parameter, body field, or header can select a tenant. On a local
install (no sign-in) it resolves to `DEFAULT_ORG_ID`, which is also the org every
pre-tenancy row was migrated into, so an existing install keeps its data.

**Joining an org** is an invitation code, not an email link: an admin generates a
single-use code (`POST /api/org/invites`) and shares it through a channel they already
trust; the colleague redeems it (`POST /api/org/join`) and lands in that org with its
funders, cards and findings. Sending mail would need a provider, a domain reputation and
a bounce story — and §8 rules out the app sending mail on anyone's behalf.

**Leaving one** has two doors, and both end in the same place. `orgs.owner_uid` records
who created the org; that person is the **admin**, and only they can remove a member
(`DELETE /api/org/members/{uid}`) or hand the org on (`POST /api/org/transfer`). Anyone
can close their own account (`DELETE /api/account`), behind typing their own address.

- **Deleting the `users` row is the revocation, and it is complete.** Every `/api` route
  resolves the caller's org through `org_for_user`, so with no row there is no org to
  resolve: findings, funders and the encrypted key all become unreachable in one write.
  Their next sign-in provisions a fresh empty org with `onboarding_done` unset, which is
  the "they start over like a new user" the removal is for.
- **Closing your own account removes the Firebase sign-in too**, so it does not quietly
  mean "your data goes and we keep your email address". Done with Identity Toolkit's
  `accounts:delete` and the caller's own ID token — **not** `firebase-admin`, which would
  want a service-account file on the box (§3). **Data first, sign-in second**, always: a
  failure that way round leaves somebody able to sign in to a fresh empty org, where the
  reverse would lock them out of an account whose data is still here. Firebase refuses to
  delete on a stale sign-in (`CREDENTIAL_TOO_OLD_LOGIN_AGAIN`, about `auth_time` — a
  token refresh does not help), so the outcome is reported separately and the UI says
  "sign in once more and try again" rather than claiming both are gone.
- **An admin with colleagues must transfer before deleting themselves**, or the last
  person who can invite or remove anyone walks out and the org is frozen.
- **A dangling owner heals** to the earliest remaining member (`org_owner`). An org with
  members and no valid owner could otherwise never remove anybody or hand itself on.
- **Last one out strands the org rather than deleting it** (`strand_org`): the findings,
  the run log, unused invites, the imported starter funders and the **encrypted API key**
  go — a live credential must not outlive the account it belonged to — and the funders
  they **added by hand** stay. That asymmetry is the point. Findings are one nonprofit's
  private research and nobody can ever ask for them again; a copy of a list we ship is
  not a contribution; a hand-added funder is researched work that the next nonprofit in
  that city can use. Settings stay too, `org_name` above all, because attributing that
  list later needs to know whose it was.

**Whether somebody is new is a stored fact** (`onboarding_done`), not a deduction. It was
re-derived from "do you have a key, a ticked program and a funder", so an established org
that unticked its last programme for an afternoon was thrown back to step one of
onboarding on an account it had used for months. Schema v9 backfills it for every org
with **evidence of use** — a member, a run, a finding or a saved key — deliberately not
"every org that exists", because the v7 migration creates `DEFAULT_ORG_ID` itself and a
first-ever boot would otherwise mark its own default org as experienced and never show
onboarding to anyone.

Otherwise the first person to sign in adopts the pre-tenancy data and everyone after gets
their own **empty** org: working settings, no funders, no program cards. A new nonprofit
must not inherit the pilot's 44 San Diego funders.

**Stubbed (present but not wired to a backend):**

- The **org switcher** shows this install's org name but cannot switch or add orgs. Now
  that orgs are real it actively misleads, and should become a plain label until there is
  something to switch to.
- The **GitHub Actions weekly cron** (`.github/workflows/weekly.yml`) and the **Google
  Sheets sink** exist but are legacy: never run in production, and superseded by the
  dashboard + on-demand runs. Scheduling for a hosted deployment should be a systemd
  timer or cron on the host, not GitHub Actions.

**Funders one nonprofit shares with the next** (`share_funders`, off by default). A
funder is not private — a name, a grants page, a sector — but "not private" is not "ours
to publish on their behalf", so an org opts in. Only `added_by='user'` rows are eligible:
re-sharing a copy of a list we already ship to everybody contributes nothing.

Nothing is offered until `app/funder_check.py` has fetched the page and found it readable
and plausibly about grants. That check **produces evidence, never a verdict**, and the
gap between the two is where the harm would live:

| question | answered? |
|---|---|
| Is the URL a real, reachable, public page? | yes — `urlguard` + the polite fetcher |
| Does it look like a grants page? | roughly — `agent/parse.py`, amounts and deadlines |
| Is this a real registered organisation? | **no** — see the IRS 990 note in §5 |
| Is it worth applying to? | **no**, and nothing here may imply otherwise |

So Discover's **Add funders** section shows the sentence and the date (*"The page opened
and names an award amount. Checked 2026-08-05."*) on a small card with the link, and no
tick. No model is involved and nothing is spent. Failing the check is disqualifying;
passing it only permits the entry to be offered, labelled as somebody else's suggestion —
and the "we have not researched these" line sits **under** that grid, word for word,
where it is the last thing read before Add rather than the first thing scrolled past.

That section is a card grid and not a column of full-width rows, which is not only
cosmetic: five shared funders as five full-width rows made the "who should I watch?"
section taller than the funder list it sits above. The page order is Add funders →
Funders it watches → Blacklist → "Find funders near you" — the last of those is disabled
and unbuilt, and it was sitting between the two things people came for.

**Anyone can report one, and one report hides it from everybody immediately**, before
review. That is the deliberate direction to fail in: hiding a good funder costs one
nonprofit one grants page they could add by hand, and leaving a bad one up costs somebody
an afternoon writing to nobody. An install admin (`FUNDWORTHY_ADMIN_EMAILS`, the same gate
as `/api/admin/stats`) then takes it down for good or dismisses the report and restores
it — the restore matters, or one objection is a permanent veto. The reporting org is
recorded and never shown to anyone.

### Pilot / seed data

The 60 researched sources in `agent/sources.py` — 58 San Diego grantmakers plus the
California and federal grant databases — are grouped into starter lists
(`agent/directory.py`) that **an org imports for itself**. Nothing is seeded into a new
account.

This has been decided three times, so the history is the argument:

1. **Into `DEFAULT_ORG_ID` alone.** Whichever account signed in first got 52 funders and
   the account created five minutes later got none — an artefact of that org existing
   rather than a decision anyone made.
2. **Into nobody.** Even, and broken: a new account opened onto an empty list, pressed
   Search, and nothing happened with no explanation anywhere.
3. **Into everybody.** Fixed (2) at the cost of handing a Chicago nonprofit 58 San Diego
   foundations they never asked for and had to prune one at a time.

Now nobody again — **but the thing that made (2) broken is gone.** Onboarding step 3 is
those lists as one-click imports, so an empty list is a question being asked rather than a
dead end, and `runner.preflight` refuses a search with no funders and names the page that
fixes it, so the silent nothing of (2) cannot recur. That step also says out loud what
nothing said before: **the funder list is the whole search.**

**What is not imported is warmth.** `Source.warm` records that the *pilot* organisation
already receives money from that funder. Copied into every org it seeded, it printed
"Existing relationship" on eight funders in the list of a nonprofit that had signed up
ten minutes earlier — an assertion about them that nobody at their organisation had made.
`import_starter_list` now imports the cold copy (and derives the sector from it, since
`sector_for` reads warmth), and schema v8 cleared the flag on rows already imported into a
non-default org that nobody has since edited. Whether a relationship exists is theirs to
state, on the funder editor.

**Program cards are not seeded, and there is deliberately no directory for them.** A
funder list is shared knowledge: who gives money, in this city. A program card describes
what *this* nonprofit does, in their words, so another org's cards are not merely
unhelpful but wrong. A new org writes its own, with the assistant drafting from a link.

---

## 3. Architecture

```
  ./start.sh ──▶ FastAPI (uvicorn, 127.0.0.1:8000) ──▶ dashboard/dist  (built React SPA)
                      │
                      ├── data/rise.db   ← SQLite (WAL): settings · programs · funders
                      │                     findings · runs · the encrypted API key
                      │   data/.fernet-key ← the key that encrypts the API key
                      │
                      └── subprocess: python -m agent.run --sink db --run-id <id>
                                        │  (one run at a time; Stop terminates it)
                                        │
                                        ├─ crawl()     fetch + parse + free filters   $0
                                        ├─ evaluate()  Haiku triage → Sonnet score  ≤ $1
                                        └─ sinks: sqlite (primary) + webjson (run.json)
```

- `app/main.py` — REST API + static host for the dashboard. Every endpoint is a small
  SQLite read/write. There is **no endpoint that returns the API key**.
- `app/runner.py` — the Re-run button. Launches the pipeline as a **subprocess** (not a
  thread) so Stop is real and a crawl crash cannot take down the settings page. One run
  at a time (a global lock) — concurrency would double-spend the budget. *This global,
  in-process run state is the main thing that has to change to scale — see FUTURE.md.*
- `app/db.py` — schema, migrations, connection. One SQLite file, no ORM.
- `app/secrets.py` — API key storage: Fernet-encrypted, write-only, resolves from
  Settings first then the environment.
- `app/assistant.py` — the "paste a link, get a program card" assistant (one Sonnet
  call, capped at $0.10). The answer to "the user never writes a prompt."
- `agent/run.py` — the pipeline entrypoint and orchestration; owns the budget ceiling
  and the stop conditions. Identical whether triggered by the button or a scheduler.
- `agent/fetch.py` — httpx with retries, robots.txt, and **one request per host at a
  time** with a politeness delay. We are a small nonprofit's agent; behave like one.
- `agent/parse.py` / `agent/filters.py` / `agent/score.py` / `agent/verify.py` — page →
  candidate → deterministic rejects → tiered LLM scoring → the accuracy gate.
- `sinks/` — `sqlite.py` (primary, what the dashboard reads), `webjson.py` (a static
  `run.json`), `sheets.py` + `jsonl.py` (optional export targets).

### Tech stack

Python 3.11+ · FastAPI + uvicorn · SQLite (WAL) · httpx · selectolax/BeautifulSoup ·
dateparser · **Anthropic API** (Haiku triage, Sonnet scoring) · cryptography (Fernet) ·
PyJWT (Firebase ID tokens — not `firebase-admin`, which would want a service-account file
on the box) · Vite + React (static build) · Firebase Auth in the browser, dynamically
imported so a local install never loads it. A headless run needs API credits, not a chat
seat.

### Environment variables

| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | **Local installs only** — the default org's fallback when sign-in is off, which is what keeps `./start.sh` zero-configuration. Setting `FIREBASE_PROJECT_ID` switches it off entirely: on a deployed box every org saves its own key, including the default one, so a key left in the VM's environment is inert rather than a bill. See `app/secrets.py: resolve_api_key` |
| `FUNDWORTHY_DB_PATH` | Override the SQLite path (default `data/rise.db`) |
| `FUNDWORTHY_KEYFILE` | Override the Fernet key path (default `data/.fernet-key`) |
| `FUNDWORTHY_PORT` | Port for `start.sh` (default 8000) |
| `FUNDWORTHY_MAX_CONCURRENT_RUNS` | How many orgs may crawl at once (default 3). A machine guard, not a tenancy rule |
| `FUNDWORTHY_STRICT_CONFIG` | Scheduled-job mode: a config that can't be read is a refusal to run, never a fallback to defaults (protects the kill switch) |
| `FUNDWORTHY_SHEET_ID` | Google Sheet id for the legacy Sheets export sink |
| `FUNDWORTHY_GITHUB_TOKEN` | A GitHub personal access token with Issues: write permission on the target repo. Unset means the bug-report form still records reports locally but cannot file them automatically |
| `FUNDWORTHY_GITHUB_REPO` | `owner/repo` to file bug reports against, e.g. `VictorKhant/Fundworthy`. No default — a fork must never silently file against the upstream repo |
| `FIREBASE_PROJECT_ID` | **Turns sign-in on.** Unset = local mode, no login |
| `FIREBASE_WEB_API_KEY` | Firebase's public web key, served to the browser. Required when sign-in is on |
| `FIREBASE_AUTH_DOMAIN` | Defaults to `<project>.firebaseapp.com`; override only for a custom auth domain |
| `FIREBASE_PASSWORD_AUTH` | `1` if the project has Email/Password enabled. Adds the password form and a real create-account flow; Google-only without it. Password accounts must confirm their address before they can sign in — `app/auth.py` refuses an unverified token |
| `ALLOWED_EMAILS` | Comma-separated. Restricts who may sign in. **Leave it out and anyone can sign up**, which is the default |
| `FUNDWORTHY_PILOT_EMAILS` | Who inherits the pre-tenancy org (its funders, findings **and saved key**). Claimed by name, never by signing in first — see `app/db.py: _claims_default_org` |
| `FUNDWORTHY_MAX_RUNS_PER_DAY` | **Off by default.** A lever for one misbehaving account, not a ration — an org spends its own key, so how often it searches is its own business |
| `FUNDWORTHY_ADMIN_EMAILS` | Who may read `/api/admin/stats` and moderate reported shared funders (`/api/admin/reports`) — the routes that cross every tenant boundary. Its own list, never `ALLOWED_EMAILS`; **unset means nobody**, so a reported funder simply stays hidden until somebody is named |
| `SITE_URL` | Build-time (dashboard). The public address, for the canonical link and sitemap. Read from the environment, then `dashboard/.env`, then the root `.env`; unset just omits them. Renamed from `VITE_SITE_URL` — the `VITE_` prefix means "expose to browser code via `import.meta.env`", and this is substituted by a plain Node script after `vite build` |

---

## 4. Data model

One normalized `Opportunity` record (`agent/models.py`); sinks render it. Fields split
into **sourced** (must be backed by a verbatim quote on the fetched page, else nulled and
`needs_human_check=True`) and **inferred** (a model judgement, always labelled as such in
the UI so it can't be mistaken for a fact off the funder's page).

**Accuracy rules — not optional:**

- **Never state a deadline or award amount that isn't on a page we fetched.** No source
  → null the field and flag it.
- `source_url` is required — no URL, no record. It points at the funder's own page or a
  named public database, and the UI shows which.
- `needs_human_check` rows sort **last** and are shown as their own block.

**A third kind of field, alongside sourced and inferred: self-evidenced.** `apply_url`
(schema v17) is neither — no model reads it and no quote gates it, because it is a real
`href` already sitting in the fetched HTML, found for free by `agent/parse.py:
find_apply_link`. It exists because `source_url` must stay the funder's own page (the
rule above), and a great many funders route the actual application through a portal
vendor — Fluxx, Submittable, SM Apply, GrantRequest — on a different host entirely.
Measured against 62 real pages from the shipped funder registry, 8 of them (13%) had
their real apply link off-domain; `source_url` could never point there without breaking
the rule that makes it trustworthy, so it is a second, separate fact instead. The
dashboard shows it as **"Go to the application ↗"**, next to and clearly distinct from
**"Open the funder's page ↗"** — never a replacement, and never shown when nothing on the
page scored as a likely apply link.

**Storage & dedup** (`app/db.py`): `opportunities.id = stable_id(source_url, title)`, and
the primary key is `(org_id, id)`, so "have we shown **this org** this already this
month?" is an index probe in the free tier — a repeat costs $0.00. Findings are
partitioned by `month_key` (`YYYY-MM`); at the start of every run, that org's rows from
earlier months are purged, so a grant seen in one month may legitimately resurface the
next.

Both halves of that are scoped per org, and it matters in opposite directions: an
unscoped **dedup** set hid grants from the second org to run each month (dropped free,
never scored, no explanation), while an unscoped **purge** let any org's Re-run delete
every other org's archive.

---

## 5. Scoring & cost control

**Tiers, cheapest first (the whole cost strategy):**

1. **Free.** Fetch + parse + deterministic filters (award floor, deadline runway,
   geography, remove list, thin-page + dedup rejects). Kills most candidates at $0.
2. **Cheap.** Haiku triage on survivors only, on stripped text.
3. **Expensive.** Sonnet scoring + rationale on the top N, where N is the result cap.

**Hard filters (free rejects), before any model call:** award below the floor
(default **$10,000**), deadline inside the runway (default 14 days), funder on the
**remove list**. Match-requirement is *flagged, not filtered*. `agent/filters.py:
apply_filters` is what enforces all of it — including the null-vs-reject distinction the
module docstring calls out by name, since a filter that rejects a missing amount empties
the pipeline and one that passes it silently defeats the floor — and `tests/test_filters.py`
now exercises it directly rather than only through `tests/calibration.py`, which pytest
never collects on its own.

**A closed grant used to read identically to one that never stated a deadline at all.**
`ParsedPage.earliest_deadline` only ever returns a future date — correct for what it's
for — but that meant a page whose *only* stated deadline had already passed collapsed
into the exact same branch as a page with no deadline anywhere: flagged
`deadline_not_stated`, scored, and shown as if still open. Found on real, currently-live
pages in the shipped funder registry — Imperial Valley Community Foundation, San Diego
Workforce Partnership, ACTA's Living Cultures Grant, and others — whose stated deadlines
had genuinely passed and were reaching the user with nothing marking them closed.
`ParsedPage.most_recent_past_deadline` is now checked whenever no future one exists, and
`apply_filters` rejects on it as `Reject.DEADLINE_PASSED` — a reject that used to be
provably unreachable (`earliest_deadline`'s own guarantee made the `days < 0` branch
dead code). A page describing both a closed round and an open one is unaffected: the
future date is found first and this path never runs.

**The deadline and amount extractors missed most `label: value` and label-above-value
layouts**, which measured against the same 62-page sample is how *most* funders publish
this, not an edge case. `agent/parse.py: _sentences()` split on a bare `:` as if it ended
a sentence, so "Deadline to apply: May 1, 2027" — one fact, one line — came apart into a
cue with no date and a date with no cue, and `extract_deadlines`/`extract_amounts`
require both in the same piece. Fixed at the root (the colon no longer splits) plus a
second, narrow pass (`_paired_with_nearby_value`) for the label-on-its-own-line case a
looser split alone cannot safely reach — loosening newline-splitting too was tried and
reverted, because it let a real multi-row timeline table (open date, submission
deadline, notification date, all one cue away from each other) collapse into one
"sentence" and pull in dates that were never the deadline. Two more real, load-bearing
edge cases came out of testing this against live pages: an "Applications open" date sharing
a run-on sentence with the real deadline used to win the `min()` in `earliest_deadline`
simply for being earlier (`_nearest_cue_wins` now requires the closer *preceding* label,
not just any cue anywhere in the sentence), and May's abbreviation being identical to its
full spelling ("may") meant every May deadline was recorded twice.

**A 2-digit year could parse a hundred years wrong, on a real currently-shipped page.**
California's CalVIP grant states "Proposals due 6/27/25" — `dateparser`, under the
`PREFER_DATES_FROM: "future"` setting `_parse_date` always uses, read this as
**2125-06-27**, not 2025. That is dangerous in a specific direction: `earliest_deadline`
only returns future dates and takes the `min()`, so a date wrongly parsed a century ahead
would always look like the deadline with unlimited runway — exactly backwards for a grant
whose real 2025 deadline had already passed. Found building the golden-fixture harness
below, not by looking for it. `_parse_date` now expands a bare 2-digit year to `20XX`
itself before either parser sees it, since a date on a page fetched today never
legitimately means a year a century out.

**The golden-fixture accuracy harness** (`tests/test_golden_fixtures.py`,
`tests/fixtures/`) is real funder HTML — not synthetic prose — with hand-labelled ground
truth a human established by reading the actual fetched page, checked against what the
pipeline actually extracts. This is the gap `tests/calibration.py`'s own docstring names
in itself ("THE FIXTURES BELOW ARE NOT MAURI'S... placeholders"): that harness is real
pages but synthetic fixtures; this one is real pages with real, verified expectations.
Two of the bugs above (the century-off date, the open-date-vs-deadline confusion) were
found *while building it*, against pages nobody had gone looking for a problem on. Stage 1
(fetch, parse, the free filters) needs no key and runs in the offline suite; stages 2/3
need a live Anthropic key the same way `calibration.py`'s full run does, so the harness
records a written, checkable prediction for what the model *should* do
(`tests/fixtures/manifest.py: expect_relevant_to_housing_org`) and a `--live` mode to
check it, rather than asserting something nobody has verified.

**`estimated_effort_hours` is anchored to what the application asks for, not the award
size.** It had no scale at all — "estimate from the ask and the award size if the page is
thin" invited anchoring the hours guess to a number that has nothing to do with how much
paperwork an application takes. It now names four concrete bands (LOI-only ~2-4h;
standard proposal ~6-10h; proposal plus audited financials/board resolution/letters of
support ~15-25h; multiple heavy attachments or a multi-stage review ~30h+), the same way
the award scale got explicit anchors above. **`time_to_funds_days` is told, explicitly,
that null is the common and correct answer** — most funder pages state nothing about
their internal review or disbursement timeline, and the prompt used to invite "estimate
from what the page says" without being blunt that "the page says nothing" is what
actually happens most of the time, which is exactly the shape of prompt that produces a
confident guess dressed as a fact.

**Both verified live** (2026-08-07, real Anthropic key, real funder pages, ~$0.10 total):
`time_to_funds_days` came back `null` on every one of 4 scored pages — none of them
stated a review cycle or notification date, and the model correctly declined to invent
one rather than treating null as a fallback for a hard case. `estimated_effort_hours`
landed inside the anchored bands on every page (8h for a thin government overview, 20h
for two substantive private-foundation pages, 30h for the one describing the heaviest
ask), not the flat, undifferentiated numbers the unanchored prompt produced before.

**The same live run found a real bug the reasoning above hadn't anticipated:**
`award_score` came back **30/30** — full marks — for a page whose own rationale said
"this is a past grant record" with "no open call." Hilton Foundation's housing-priorities
page shows a $2.4M grant already given to someone else in 2022 as a case study — the free
tier's `_AWARD_DISQUALIFIER` already correctly refuses to read that as `page.award_max`,
but the *scoring* prompt had no equivalent instruction, so Sonnet's own `award_score`
judgement used the same historical figure as if it were an offer to a new applicant.
Fixed by extending the null rule: a page whose only dollar figures describe money already
disbursed is null, exactly like a page naming no figure at all. Re-verified twice after
the fix, same page: `award_score` came back null both times and the total score corrected
from an inflated 53 to a correct 37 — nothing else about the page changed. The manifest
entries this was found on (`tests/fixtures/manifest.py`: `hilton_foundation`,
`enterprise_community`, `melville_trust`) also had their own relevance predictions
corrected during the same run — the original predictions conflated "is this funder a
good topical fit" with "does this specific fetched page describe an actionable open
call," which triage correctly treats as different questions; a foundation's homepage is
not an open call regardless of how well its mission matches. That conflation was
structural, not just a wrong prediction on three rows: the manifest had one field,
`expect_relevant_to_housing_org`, doing both jobs. It is now two —
`expect_actionable: bool | None` ("would a human call THIS fetched page something you
can apply to right now") and `expect_relevant: dict[str, bool | None]` (per program
slug, "is this a plausible topical fit") — so a future fixture cannot repeat the mistake
by construction; the live check computes the expected triage answer as their
conjunction (`actionable AND relevant to at least one active program`), the same
question `_TRIAGE_RULES` actually asks.

**A single stated floor was reported as the ceiling, on a real currently-shipped page.**
Hearst Foundations' Health funding-priorities page states exactly one dollar figure:
"Minimum grant size is $100,000." `ParsedPage.award_max` and `award_min` both resolved
to `min()`/`max()` over the same one-item evidence list, so a stated *floor* — the least
you could receive — was reported as the *ceiling*, telling a nonprofit a large health
funder capped every award at $100,000 when the page makes no such claim. Found while
expanding the golden-fixture set (below), not by looking for it. `agent/parse.py:
_FLOOR_ONLY_CUE` / `Evidence.floor_only` now marks a sentence that states only a floor
("minimum...", "at least $X", "grants starting at $X") with no ceiling anywhere in the
same sentence (a range, or "up to $X", cancels it — both numbers are real evidence for
their own side, unchanged), and `award_max` excludes floor-only evidence while
`award_min` still includes it. Same real sentence, before and after:
`award_max=100_000, award_min=100_000` → `award_max=None, award_min=100_000`. Re-verified
live: Sonnet's own extraction agreed independently (`award_min_stated=100000,
award_max_stated=null`) even before this fix touched the free tier, which only ever fed
the deterministic floor filter and the `--no-llm` placeholder — the paid tier was reading
it correctly on its own.

**Picking Haiku to score was a live 400 on every candidate, silently.** `MODEL_CHOICES[3]`
has always offered Haiku as a scoring model ("cheapest, but scoring is the judgement you
are actually paying for"), but `score_one()` sent `thinking={"type": "adaptive"}`
unconditionally — which Haiku rejects outright, not a documented limitation. An org that
picked it would have every single scoring call fail and the run abort once
`CONSECUTIVE_ERROR_LIMIT` (five) was reached, with a note about "tier 3 could not read"
and no indication the model choice itself was the cause. Confirmed live (both the break
and the fix): `score_one()` with `scoring_model=haiku` raised `BadRequestError: adaptive
thinking is not supported on this model` before the fix and returned a real score (42,
fit 8/60) after it. `agent/score.py: _model_supports_effort` is the one gate both
`triage()` and `score_one()` now check before adding `thinking`/`effort` to a call —
found and fixed alongside the new per-stage effort setting (above), but a pre-existing
bug independent of it.

**The Opus scoring option was a retiring model.** `claude-opus-4-1` retires 2026-08-05;
`MODEL_CHOICES[3]`'s Opus entry pointed at it. Migrated to `claude-opus-5`, which is also
cheaper ($5/$25 per Mtok vs. the old model's $15/$75) — a straight improvement, not just
a retirement fix. The picker's own cost note ("five times Sonnet's price") was corrected
to match: Opus 5 is a consistent ~1.67x Sonnet's price on both input and output, not 5x.

**The golden-fixture harness grew from 12 real pages, one program, to 34 real pages,
four program cards across two organizations** — New Destiny Housing's HASS plus RISE San
Diego's ARTS/RULFP/RESILIENCE (`tests/fixtures/manifest.py`: `PROGRAMS`,
`ORG_FOR_PROGRAM`, real cards from `app/db.py: SEED_PROGRAMS`, not invented) — so a
page's relevance to one program and its irrelevance to the other three are asserted on
the same real fetch, not assumed by omission. Every fixture is now judged on two
separate axes (`expect_actionable`, `expect_relevant` — see above), and
`test_golden_fixtures.py --live` computes recall/precision/accuracy against their
conjunction instead of a bare agreement count. Live-run once against both orgs
(2026-08-07, ~$0.18 total): **100% recall, 88.5% accuracy, 40% precision, 12.5% false
positive rate at the triage stage** (TP=4 FP=6 TN=42 FN=0, n=52). The six "false
positives" are not the same failure repeated six times: `sdge-guidelines` (a real, if
informal, corporate-giving process that explicitly rules out arts funding by name)
correctly self-corrects at scoring — fit 14/60, score 23/100. The other five (`hud_coc`,
`robin_hood_nyc`, `ca-arts-council`, `creativewest-grants`, `kellogg_leadership`) are
directory/overview pages for a **genuinely strong topical fit** — HUD's CoC really is
the core federal vehicle for exactly what HASS does; Robin Hood really is NYC's largest
anti-poverty funder — and triage answering yes on a thin-but-real page is the documented,
intended behaviour (`_TRIAGE_RULES`: "Answer TRUE when it is a real, open call, even if
the page is thin"). Scoring confirms this rather than contradicting it: all five landed
fit-only (award/timing null, exactly the renormalisation rule above), scores 63–87,
`needs_human_check` set on the ones that were truly empty of content. Triage's job is a
permissive first pass on a strong-fit page it cannot yet confirm has a specific open
call; scoring is where the real precision happens, and on this sample it did.

**There is no sector filter either, and it went the same way** (R8). Four checkboxes —
"warm_partner / foundation / government / arts_agency" — narrowed the funder list, on a
taxonomy we invented and the settings copy admitted was a guess. A funder's bucket came
from the shipped registry or defaulted to `foundation` for anything typed in, so
unticking a box excluded funders on a label nobody at the nonprofit had chosen, silently,
in the free tier. `sectors_active` stays in the schema and the API so old rows read back;
nothing reads it. Which funders are searched is the funder list.

**There is no geographic filter, on purpose.** There was one, and it is removed rather
than fixed: where an org can apply is decided by *which funders it chose to search*, not
by pattern-matching prose on a page we already decided to fetch. A text filter got it
wrong in both directions — rejecting national programs that happened to name a state,
passing regional ones that never named their region — and it did so silently, in the free
tier, which explains nothing to anyone. `org_location` is now only a hint about which
funders to show first. See the note at the top of `agent/filters.py`, and FUTURE.md §4a
for the funder directory that replaces the idea properly.

**Three things you can do to a funder, and they are different.** Pause (`active=0`)
takes them out of this week's search and leaves them on the list; **block** (`blocked=1`)
also stops them ever being *offered* again, by a researched list or by another
nonprofit's suggestion; delete removes the row. Blocking needed its own column precisely
because `active` does not reach the two places that offer a funder — an org that unticked
one got it back from every import.

Blocking reached the database and stopped there for a while: `repo.update_funder` handled
the column correctly, but `FunderIn` — the request model behind `PUT /api/funders/{id}` —
had no `blocked` field, so Pydantic silently dropped it from the request body before the
handler ever saw it. The dashboard's Block control showed a confirm dialog promising the
funder would never be offered again, then got a 200 back having changed nothing. Fixed by
adding the field to `FunderIn`; `tests/test_api.py::test_blocking_a_funder_through_the_api_actually_persists`
goes through the real HTTP layer rather than calling `repo.update_funder` directly, which is
what let the gap through in the first place.

**The remove list** is the single exclusion lever, and it is the user's: a funder (or a
single named program, matched on page title) that is un-ticked is never fetched, never
triaged, never scored. Existing funder relationships go here — the org already receives
that money and doesn't want to reapply, so a relationship is a reason to *exclude*, never
to rank higher. The model is never told whether the org knows a funder.

**Score (0–100)** = program fit **60** + award size vs the floor **30** + can-the-app-be
-finished-before-the-deadline **10**. Funder warmth is not a factor.

**Fit carries most of the score, deliberately.** It was 40/35/25 (fit/award/timing) and is
now 60/30/10. Fit is the one component that is never null — the page and the org's own
programs are always in front of the model — so it is the axis every candidate can actually
be judged on. Timing shrank the most: it leans on `estimated_effort_hours`, the model's own
per-page guess at how long an application takes, which has no ground truth to check it
against and is noticeably less reliable than "does the page state an amount." A quarter of
the score riding on that guess was more confidence than the estimate earned; a tenth is
still enough to separate a two-page letter of interest from an audited-financials
application closing in three weeks, without a shaky number swinging the ranking on its own.

**The model returns the three parts, not the total** (`agent/score.py: ScoreParts`,
`compose_score`). It used to return one number and the weights were three lines of English
inside a prompt that nothing enforced, so "the weighted score" was really a holistic guess
at a sum. Composing it in Python enforces the weights and makes a score decomposable —
"why is this 38?" had no answer anywhere in the app, and now it is a row in the database
and a breakdown under "More details".

**A component with nothing to judge it on is `null`, and null leaves the denominator**
rather than scoring zero. This is the fix for the thing that made the whole list
unreadable. Award size and timing both need the funder to have published something, and
most funders publish neither — so under the original 40/35/25 split, 60 of the 100 points
were unearnable for the median candidate, every score was really out of 40, and the list
topped out at 42. That reads as "we found you nothing good" when what actually happened is
that grant-makers write terse web pages. Scoring a missing component zero is a *claim*: it
says this opportunity was tested on award size and failed. It was not tested. So today,
`fit 42/60, award null, timing 7/10` is 49 earned out of 70 available → **70**, and the row
says what it was and was not scored on. It is the same rule as §6's "amount not stated" —
we do not invent the number, and we do not punish its absence either. `fit_score` is never
null: the page and the program cards are always in front of the model, so fit is always
answerable and a run always has one axis every candidate shares.

**The prompt is the org's own, and this was a multi-tenancy leak.** Every scoring call
opened with a hardcoded *"a nonprofit working across San Diego County and Imperial
County"* — `org_name` and `org_location` reached the database and the dashboard and
stopped there. Program fit is the single largest component of the score, so every nonprofit
outside San Diego had it decided against the wrong region. An empty field is passed through
as an empty field; a guessed region is the thing that broke this. The hours an application
may cost is theirs too (`max_effort_hours`, default 10, set on **"Adjust search settings"**
on This week) — 10 points are measured against it and it was one nonprofit's staffing
applied to every tenant.

**The prompt does not tell the model to score low.** "Be strict" sat in the *shared*
preamble, so it biased Haiku triage — the cheap binary filter deciding what is even worth
paying to read — as well as scoring. The award floor already does that job,
deterministically, for free, before any model runs. **And the award scale has anchors**
(at the floor ≈ 9/30, 3× ≈ 21/30, 10× ≈ 30/30): "relative to the floor" with no scale
defined resolves downward, because an undefined scale plus an instruction to be strict is
answered conservatively every time.

`tests/calibration.py` is the harness that catches a regression here, and it no longer
asserts only that every YES outranks every NO — that passed on the 13–42 distribution.
It measures ordering (AUC), spread, and headroom via `agent/evalmetrics.py`.

**Nothing about the funder's finances is, either — the IRS 990 lookup is gone** (schema
v12). It called ProPublica's Nonprofit Explorer once per funder and put one line into the
Sonnet prompt: the funder's revenue and expenses. Two things were wrong with that, and
they compound:

- The prompt told the model to judge **program fit** from the funder's *past grants*.
  The lookup never returned past grants — that is Schedule I / 990-PF Part XV, which the
  API does not expose cheaply — so the model was asked to reason about giving history
  and handed a balance sheet.
- It resolved for roughly **half** the list. A state arts council, a county initiative and
  a fund inside a community foundation file no 990 at all, and a short name like
  "MacArthur Foundation" matches nine organisations, so the lookup correctly refuses
  rather than attaching Roderick MacArthur's finances to somebody else's name. Two
  near-identical grants could therefore score differently because of an attribute of the
  funder's legal filing status, which is not a fact about either grant.

Removing it does not move the average score; it removes an input that was inconsistent
across funders and irrelevant to fit. **Whether a funder is worth applying to is decided
from their grants page and the org's program cards, and from nothing else.**

**Budget & stop conditions.** Default ceiling **$1.00/run**; the run aborts and logs
`stop_reason: budget` if exceeded. A run ends on the first of: `target_met` (cap
reached), `budget`, `sources_exhausted`, `disabled`, `no_api_key`, `no_funders`, or
`error`. It's a **cap, not a quota** — the agent will not pad with weak results to hit a
number.

**A search that cannot work is refused, not run.** `app/runner.py: preflight` is the one
place that decides, and it answers in sentences meant for the user rather than in codes:
no key, no ticked program, an empty funder list, or a funder list nothing in the ticked
sectors matches. `RunManager.start` refuses on it (409) and `GET /api/state` returns the
same list, so the greyed-out button and the error carry **the same words** — a button
that says one thing and an error that says another is how somebody concludes the app is
broken. The pipeline keeps its own guards for the CLI and the scheduler.

The keyless case is the one that mattered. It used to shrug (`use_llm = False`), crawl
every funder for five to ten minutes and score none of them, and hand back an empty list
with no explanation on it. `--no-llm` is still the honest way to ask for the free tiers,
and still works.

**A failure reading the funder list is not the same as having none, and the run note now
says which one happened.** `sources_from_db` (`agent/sources.py`) falls back to the shipped
registry — the pilot's San Diego/California funders — whenever the org's own funders table
is unavailable, which is correct for a fresh clone with no database yet. It used to fall
back the same silent way for a real read failure on an *existing* database (lock
contention from another org's concurrent run, a corrupt row), with no log line and a run
note claiming "no funders database found" — false, and the one place a non-default org
would have seen its search quietly switch to someone else's regional funder list. The
exception is now logged (`log.error`, with traceback), and `resolve_sources`
(`agent/run.py`) checks whether the database file actually exists before choosing which
note to write, so "no database yet" and "couldn't read yours — see the technical log" are
never conflated.

**Kill switch.** The `enabled` setting. If off, a run exits before any network call. In
`FUNDWORTHY_STRICT_CONFIG` mode a config that can't be read is a refusal to run, so an
outage can't silently re-enable a switched-off agent.

**The weekly search is a separate switch, and it is off by default.** `schedule_enabled`
(read only by `app/scheduler.py`) decides whether a search happens unattended;
`enabled` decides whether anything happens at all. They were one setting, which cost
twice:

- **Turning off automation greyed out "Search again now".** An org that only wanted to
  stop the Wednesday job could not run a search by hand at all, and nothing on the
  checkbox said it would do that.
- **Every new account was scheduled for Wednesday 11pm.** That was the pilot's answer to
  a question no other org had been asked, and it meant an unattended job spending a
  nonprofit's own Anthropic credit on a schedule they never chose. A default that spends
  somebody's money has to be opted into, so onboarding asks — as an optional step where
  skipping is a real answer — and `schedule_day` is now just the value the picker opens
  on, not a decision anybody made.

The manual button is gated by the kill switch and by `runner.preflight`, never by the
schedule.

**`enabled` has no control in the settings panel, on purpose.** Offering "pause
everything" next to the schedule made them read as alternatives when they are nothing of
the sort: one means "don't search on Wednesdays", the other means "this app does nothing
now". Pausing is what the automation checkbox is for; not searching is what not pressing
the button is for. The setting still exists for the CLI, an operator, and
`FUNDWORTHY_STRICT_CONFIG` — and if it is ever false the dashboard says so and offers a
**Turn it back on** button, so its absence cannot strand anybody behind a greyed button
with no way to ungrey it. The status strip's first item reports the automation, which is
the fact that actually varies between accounts; "Fundworthy is on" was true of every
account that ever existed.

Never send a full HTML page to a model.

---

## 6. Running it

```bash
./start.sh                 # deps + dashboard build + API on http://localhost:8000
./start.sh --dev           # + Vite dev server on :5173 (hot reload)
./start.sh --rebuild       # force a fresh dashboard build

python -m agent.run --no-llm          # free tiers only, $0.00, no key
python -m agent.run                   # + LLM scoring; needs a key; ~$1/run ceiling
python -m agent.run --dry-run         # crawl + report, write nothing
python -m pytest tests/ -q            # the test suite (offline, no key)
```

Setup: open the page → **Settings** → paste an Anthropic API key → **Check it works**.
Everything else (funders, programs, this month's findings) is already seeded.

---

## 7. Repo layout

```
├── start.sh                     one command to run everything
├── app/                         FastAPI backend
│   ├── main.py                  REST API + static host for the SPA
│   ├── auth.py                  Firebase sign-in: token verification + allow-list
│   ├── db.py / repo.py          SQLite schema, migrations, CRUD (all org-scoped)
│   ├── secrets.py               encrypted, write-only API-key storage, per org
│   ├── runner.py                the Re-run button (subprocess + live log)
│   ├── archive.py / export.py   monthly dedup/purge · CSV export
│   ├── scheduler.py             the weekly run, per org, on their own day and hour
│   ├── stats.py                 `python -m app.stats` — how the install is doing
│   └── assistant.py             "paste a link → program card" (Sonnet)
├── agent/                       the pipeline
│   ├── run.py                   entrypoint, orchestration, budget ceiling
│   ├── directory.py             starter funder lists an org imports from
│   ├── fetch.py / parse.py      polite fetch · page → candidate
│   ├── urlguard.py              public-addresses-only check (SSRF), per redirect hop
│   ├── filters.py               free deterministic rejects (geography reads org_location)
│   ├── score.py / verify.py     Haiku→Sonnet scoring · the accuracy gate
│   ├── sources.py / apis.py     funder registry · CA Grants Portal + Grants.gov
│   ├── sd_funders.py            44 researched pilot funders (seed data)
│   └── models.py                the Opportunity dataclass
├── sinks/                       sqlite (primary) · webjson · sheets · jsonl
├── dashboard/src/               React UI (sidebar, dashboard, archive,
│                                 discover funders, settings, first-run tutorial)
├── tests/                       pytest — calibration.py is the ranking test,
│                                 test_tenancy.py is the org-isolation test,
│                                 test_filters.py is the free-tier filter test,
│                                 test_golden_fixtures.py + fixtures/ is the real-page
│                                 accuracy harness (real funder HTML, hand-labelled
│                                 ground truth, run `--live` for the model-tier check)
├── docs/DEPLOY-ORACLE.md        putting it on an Oracle free-tier VM
├── docs/ACCESS.md               getting into the running system (SSH · Firebase · Oracle)
├── docs/UPGRADE.md              deploying the tenancy update onto a live box
├── scripts/deploy.sh            push-to-deploy: drain · wait · back up · test · restart
├── .github/workflows/deploy.yml push to main → the VM updates itself
├── CLAUDE.md                    this file — current state
└── FUTURE.md                    the roadmap (multi-tenant, accounts, scale)
```

---

## 8. Non-goals — still refuse these

- ❌ Writing or submitting applications. The agent stops at a ranked, sourced list.
- ❌ Sending email on anyone's behalf.
- ❌ Any unbounded loop. Every run has a hard cost ceiling and a hard stop.
- ❌ A workflow that requires the user to write a prompt.
- ❌ Any accuracy shortcut. No URL → no record; no sourced quote → null the field.

Multi-tenancy, accounts, auth, and scale are **not** non-goals anymore — they are the
next phase. They are just not built yet. See [FUTURE.md](FUTURE.md).
