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
  returns the verbatim sentence it came from and that sentence is on the fetched page.
- Dashboard controls: award floor, deadline runway, result cap, spend limit, sector
  selection, program cards with CRUD + an AI "build from a link" assistant, an editable
  funder list, a monthly archive, a Re-run button with a live streaming log, a real Stop.
- Settings page storing the Anthropic API key **encrypted at rest, write-only** (no
  endpoint ever returns it).
- CSV export of the week's findings.
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

**Multi-tenant storage** (schema v7). Every row has an owner. `orgs` and `users` tables;
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

### Pilot / seed data

The 60 researched sources in `agent/sources.py` — 58 San Diego grantmakers plus the
California and federal grant databases — are grouped into starter lists
(`agent/directory.py`) and **every new org is given all three**. They can then be added to
or removed on **Discover funders**.

That took two attempts. They were originally seeded into `DEFAULT_ORG_ID` alone, so
whichever account signed in first got 52 funders and the account created five minutes
later got none — an artefact of that org existing rather than a decision. Giving nobody
them fixed the unfairness and broke the product: a new account opened onto an empty list,
and a Re-run with no funders does nothing at all. Everyone getting the same lists is even
*and* works on the first click.

The cost is that a nonprofit outside San Diego starts with 58 funders that are not near
them. That is the lesser problem — "some of these are not mine, let me remove them" beats
"the app did nothing" — and Discover funders is where it gets fixed.

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
                                        ├─ enrich_990() one-time IRS 990 lookup/funder
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
| `ANTHROPIC_API_KEY` | Fallback key for the **default org only**. A signed-in org that has not saved its own key gets none rather than quietly billing the deployer's — see `app/secrets.py: resolve_api_key` |
| `FUNDWORTHY_DB_PATH` | Override the SQLite path (default `data/rise.db`) |
| `FUNDWORTHY_KEYFILE` | Override the Fernet key path (default `data/.fernet-key`) |
| `FUNDWORTHY_PORT` | Port for `start.sh` (default 8000) |
| `FUNDWORTHY_MAX_CONCURRENT_RUNS` | How many orgs may crawl at once (default 3). A machine guard, not a tenancy rule |
| `FUNDWORTHY_STRICT_CONFIG` | Scheduled-job mode: a config that can't be read is a refusal to run, never a fallback to defaults (protects the kill switch) |
| `FUNDWORTHY_SHEET_ID` | Google Sheet id for the legacy Sheets export sink |
| `FIREBASE_PROJECT_ID` | **Turns sign-in on.** Unset = local mode, no login |
| `FIREBASE_WEB_API_KEY` | Firebase's public web key, served to the browser. Required when sign-in is on |
| `FIREBASE_AUTH_DOMAIN` | Defaults to `<project>.firebaseapp.com`; override only for a custom auth domain |
| `FIREBASE_PASSWORD_AUTH` | `1` if the project has Email/Password enabled. Adds the password form and a real create-account flow; Google-only without it. Password accounts must confirm their address before they can sign in — `app/auth.py` refuses an unverified token |
| `ALLOWED_EMAILS` | Comma-separated. Restricts who may sign in. **Leave it out and anyone can sign up**, which is the default |
| `FUNDWORTHY_PILOT_EMAILS` | Who inherits the pre-tenancy org (its funders, findings **and saved key**). Claimed by name, never by signing in first — see `app/db.py: _claims_default_org` |
| `FUNDWORTHY_MAX_RUNS_PER_DAY` | **Off by default.** A lever for one misbehaving account, not a ration — an org spends its own key, so how often it searches is its own business |
| `FUNDWORTHY_ADMIN_EMAILS` | Who may read `/api/admin/stats`, the one route that crosses every tenant boundary. Its own list, never `ALLOWED_EMAILS`; **unset means nobody** |
| `VITE_SITE_URL` | Build-time (dashboard). The public address, for the canonical link and sitemap. Unset just omits them |

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
**remove list**. Match-requirement is *flagged, not filtered*.

**There is no geographic filter, on purpose.** There was one, and it is removed rather
than fixed: where an org can apply is decided by *which funders it chose to search*, not
by pattern-matching prose on a page we already decided to fetch. A text filter got it
wrong in both directions — rejecting national programs that happened to name a state,
passing regional ones that never named their region — and it did so silently, in the free
tier, which explains nothing to anyone. `org_location` is now only a hint about which
funders to show first. See the note at the top of `agent/filters.py`, and FUTURE.md §4a
for the funder directory that replaces the idea properly.

**The remove list** is the single exclusion lever, and it is the user's: a funder (or a
single named program, matched on page title) that is un-ticked is never fetched, never
triaged, never scored. Existing funder relationships go here — the org already receives
that money and doesn't want to reapply, so a relationship is a reason to *exclude*, never
to rank higher. The model is never told whether the org knows a funder.

**Score (0–100)** = program fit **40** + award size vs the floor **35** + can-the-app-be
-finished-before-the-deadline **25**. Funder warmth is not a factor. The 990 is shown as
data, never scored.

**Budget & stop conditions.** Default ceiling **$1.00/run**; the run aborts and logs
`stop_reason: budget` if exceeded. A run ends on the first of: `target_met` (cap
reached), `budget`, `sources_exhausted`, `disabled`, or `error`. It's a **cap, not a
quota** — the agent will not pad with weak results to hit a number.

**Kill switch.** The `enabled` setting. If off, a run exits before any network call. In
`FUNDWORTHY_STRICT_CONFIG` mode a config that can't be read is a refusal to run, so an
outage can't silently re-enable a switched-off agent.

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
│   ├── irs990.py                one-time IRS 990 lookup, cached
│   └── models.py                the Opportunity dataclass
├── sinks/                       sqlite (primary) · webjson · sheets · jsonl
├── dashboard/src/               React UI (sidebar, dashboard, archive,
│                                 discover funders, settings, first-run tutorial)
├── tests/                       pytest — calibration.py is the ranking test,
│                                 test_tenancy.py is the org-isolation test
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
