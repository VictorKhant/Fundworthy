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

## 1. Now — host the single-tenant app for the pilot org

Before any multi-tenant work, get the current app hosted so the pilot org can use it.
This is the existing single-tenant build, unchanged.

- Follow [docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md): Oracle Always-Free ARM VM →
  app as a `systemd` service → nginx in front → HTTPS → sign-in (§8).
- ~~**Auth is the one real blocker.**~~ **Shipped** — see §2. Set `FIREBASE_PROJECT_ID`
  and `ALLOWED_EMAILS` in the VM's `.env` as part of the deploy; the app refuses to start
  half-configured, so there is no window where it is reachable and open.
- **Idle reclamation:** Oracle can reclaim Always-Free compute that looks idle over a
  7-day window. A once-a-week app is a candidate. Mitigate with a light periodic
  health ping, or upgrade the account to Pay-As-You-Go (keeps the free resources, exempts
  them from reclamation).
- **Backups:** automate a copy of `data/rise.db` **and** `data/.fernet-key` off-box
  (Object Storage). Losing the Fernet key means the encrypted API key is unrecoverable.

---

## 2. Auth (Firebase) — ✅ shipped

Was the prerequisite for exposing the app; it is built. Moved to
[CLAUDE.md](CLAUDE.md) §2. In short: Google sign-in through Firebase, the ID token
verified in `app/auth.py` against Google's public keys, one dependency on the whole
`/api` router, and an `ALLOWED_EMAILS` allow-list that the app refuses to start without.

What it is **not** yet, and what multi-tenancy will need:

- **One allow-list, not per-org membership.** `ALLOWED_EMAILS` is a flat env var. Real
  tenancy needs users and orgs in the database, with a join table — probably keyed on the
  Firebase `uid`, which `verify()` already returns and nothing currently stores.
- **No roles.** Everyone on the list can do everything, including replace the API key and
  start a run. Fine for one org of two or three people; not fine at scale.
- **`org_id` should ride on the token.** Firebase custom claims are the natural carrier
  once §4.1 exists, so a request arrives already scoped rather than looking its tenant up.
- **Sign-up is closed by design.** Somebody edits `.env` and restarts. Self-serve onboarding
  (§3) is what changes that, and it is the point at which the allow-list must move into
  the database.

---

## 3. Onboarding — the BYO-key cliff

BYO-key's cost is friction: the user has no AI experience, and "go to console.anthropic
.com, add a card, create a key, paste it" is the steepest step in the whole product. The
money is small (~$2–6/org/month); the *setup* is the barrier.

- A **guided onboarding walkthrough** for every new org, including a screenshot-by-
  screenshot "how to get your Anthropic API key" guide.
- **Validate the key the moment it's pasted.** The endpoint already exists
  (`POST /api/settings/api-key/test`, one-token call) — surface it in onboarding as an
  instant "that key works" / "that key was rejected" check.
- Keep the door open for a later **hybrid**: a shared trial key with a tight per-org
  weekly budget cap, so an org sees value before setting up its own key.

---

## 4. Multi-tenant re-architecture

In rough order of effort. None of it needs a bigger VM.

1. **Tenant isolation.** Add an `org_id` to every table (`app/db.py` schema) and scope
   every query. All state is currently global (one shared `data/rise.db`, one shared key).
2. **SQLite → managed Postgres, off-box.** The store uses raw `sqlite3` with SQLite-only
   pragmas (WAL, `busy_timeout`) and `ON CONFLICT` patterns, so this is a real port of
   `app/db.py` + `app/repo.py`. Use the provider's connection pooler (Neon/Supabase ship
   pgBouncer-style pooling) — many workers exhaust a managed free tier's direct
   connections otherwise. Watch each provider's idle policy (Neon auto-suspends after
   ~5 min; Supabase free pauses after 7 days).
3. **Per-tenant API keys.** Mostly there already (`app/secrets.py` stores an encrypted
   per-install key). Key it by org. The Fernet secret now guards *everyone's* keys — it
   moves to a server env var and must be backed up.
4. **⭐ Job queue — the load-bearing change.** Today `MANAGER = RunManager()`
   (`app/runner.py`) is a per-process singleton that allows **one run at a time** with its
   live log held **in process memory**. That's why you can't just add uvicorn workers
   (each gets its own `MANAGER`; two could double-spend a budget; `/api/runs/current`
   only sees its own worker's run). Replace it with a real queue (Arq/RQ/Celery) + a
   worker pool, and move run state and logs into the DB (the `runs.progress` column
   already exists to extend). Because keys are per-tenant, rate limits are per-tenant, so
   running many orgs' pipelines concurrently is safe — this is what unlocks real
   multi-tenancy.
5. **Shared fetch cache — still worth it under BYO-key.** Not for cost (each org pays its
   own) but for **politeness**: N orgs crawling the same ~50 funder sites every week =
   N hits from one server IP in a burst, which the polite crawler in `agent/fetch.py`
   can't prevent across tenants. A shared URL+week cache protects funders (and the IP)
   from that.
6. **Per-org config replaces the pilot seed.** The seeded SD funders, program cards, and
   San Diego/Imperial geography (`SERVICE_AREA_GEOGRAPHY`) become per-org settings an
   org sets during onboarding, instead of shipped defaults.

---

## 5. Why the VM is not the scaling bottleneck (reference)

When "will it handle 1000 users?" comes up: the free Oracle ARM box (4 cores / 24 GB) is
a capable machine. The order in which things actually break as you scale — and the VM's
raw compute is never near the top:

1. **Anthropic API cost** — solved by BYO-key.
2. **Anthropic rate limits** — per-tenant under BYO-key.
3. **Polite-crawler collisions** on shared funder sites — needs the shared fetch cache (§4.5).
4. **The single-run lock + in-process run state** — needs the job queue (§4.4).
5. **SQLite write concurrency** — needs Postgres (§4.2).

Near-term reality is dozens of orgs, not 1000 concurrent. A single free VM handles that
with room to spare; the fix if it's ever outgrown is a second free VM as a worker, not a
rewrite.

---

## 6. Ops & repo hygiene

- **Branch strategy.** `main` is the single source of truth (protected). Then two
  branches: a **backup** branch (last-known-good, only fast-forwarded once a state is
  confirmed working in production) and a **dev** branch (new code + testing, merged to
  main via PR).
- **Protect `main`** on GitHub: require a PR before merge, no direct pushes, no force-push.
  (Needs admin on the repo — see the note when this was set up.)
- **Push-to-deploy CI/CD.** On merge to `main`, the VM pulls and restarts the service.
  Options: a GitHub Action over SSH, or a small webhook/poll on the VM. Requires the VM
  to exist first, so it comes with/after hosting.
- **Replace the legacy scheduler.** `.github/workflows/weekly.yml` (GitHub Actions cron
  reading Google Sheets config) is superseded. On the VM, schedule the weekly run with a
  `systemd` timer or cron against `python -m agent.run`. Retire the Google Sheets sink
  and its service-account credential unless an org actually wants Sheets export.

---

## 7. Still-open product questions

Carried over from the pilot intake, not yet answered:

- Can the org meet a 1:1 **match requirement**? Currently flagged, not filtered.
- The **calibration fixtures** in `tests/calibration.py` are not the pilot's own — a pass
  proves the pipeline ranks, not that it's calibrated to a real reviewer's judgement.
- **Beyond-partners discovery** (`agent/discovery.py`) is a seam with a null provider;
  the actual discovery implementation is unbuilt.
