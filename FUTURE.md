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
- **The weekly schedule still does not exist on the VM.** A systemd timer per org is the
  shape, and under BYO-key it has to resolve *each org's* key from the database and run
  per-org — a single global cron run would use whatever `ANTHROPIC_API_KEY` is in `.env`.
- **Protect `main`** on GitHub: require a PR, no force-push.

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

- **Protect `main`** on GitHub: PR required, no direct pushes, no force-push.
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

## 10. Still-open product questions

- Can the org meet a 1:1 **match requirement**? Currently flagged, not filtered.
- The **calibration fixtures** in `tests/calibration.py` are not the pilot's own — a pass
  proves the pipeline ranks, not that it is calibrated to a real reviewer's judgement.
- **Beyond-partners discovery** (`agent/discovery.py`) is a seam with a null provider.
- **Nothing tells a user what a run cost them**, before or after.
- **No privacy policy, terms, or data-retention statement**, and no way for an org to
  delete its data. We now hold other organisations' information on a US cloud VM.
