# Rise-Fund-Finder

Weekly funding-opportunity agent for **RISE San Diego**, built at the AI Trailblazers
Social Impact Hack-AI-thon (San Diego, Aug 1–2 2026). RISE San Diego owns this work.

It watches the funders RISE already has relationships with, and each Wednesday night
leaves a short, sourced, ranked list in a Google Sheet for Thursday morning.

**The problem it solves is not "find more grants."** RISE's COO already spends ~16
hours a week finding grants; the problem is that most of what she finds is too small to
justify a 10-hour application. So this agent is built to return *few* results, and to
say "amount not stated" rather than guess. See `CLAUDE.md` §1.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m agent.run --no-llm            # free tiers only, $0.00, no key
```

```bash
.venv/bin/python -m agent.run                     # + scoring; needs ANTHROPIC_API_KEY
.venv/bin/python -m agent.run --dry-run           # crawl and report, write nothing
.venv/bin/python -m agent.run --budget 0.25       # tighter spend ceiling for this run
.venv/bin/python -m agent.run --max-tier 2        # widen scope to intermediaries
.venv/bin/python -m agent.run --sink sheets       # needs RISE_SHEET_ID + service account
.venv/bin/python -m tests.calibration --dry-run   # the §10 test, filters only
```

## Where things are

| Path | What |
|---|---|
| `CLAUDE.md` | The spec. Read it first. |
| `.github/workflows/weekly.yml` | The Wednesday-night cron, secrets, and 20-min timeout |
| `agent/sources.py` | Which funder pages get watched, and how much we trust each URL |
| `agent/parse.py` | Page → candidate. The hard part. |
| `agent/filters.py` | The §7 hard rejects. Free — they run before any model call. |
| `agent/score.py` | Haiku triage → Sonnet scoring, behind a hard $1.00 ceiling |
| `agent/config.py` | Reads the Config tab — including the `ENABLED` kill switch |
| `sinks/sheets.py` | The Google Sheet. The Sheet is the product. |
| `tests/calibration.py` | The §10 test. "The only test that matters." |
| `dashboard/` | Read-only run history. Vite + React on Vercel. |
| `HANDOFF.md` | For RISE. Plain language, no developer required. |
| `STAKEHOLDER.md` | Open questions, answers, commitments |
| `evidence/` | What we ran, what broke, what we corrected |

## Status

**Block 1 complete** (§12): registry → fetch → parse → normalized record → sink, run
against live funder pages. 6/6 tier-1 sources fetch, every record carrying a real
`source_url`.

**Block 2 — free tiers verified, paid tiers unrun.** The §7 hard filters reject 11 of
28 live pages and 5 of 5 calibration NOs at **$0.00**, with no YES wrongly killed.
Haiku triage and Sonnet scoring are written and statically checked but have **never
run** — no `ANTHROPIC_API_KEY` in this environment. Projected cost when they do:
~$0.42/run, ~$1.81/month, against §8's $1.00/run ceiling.

**Block 3 complete.** Cron fires 06:00 UTC Thursday = **Wed 23:00 PDT / 22:00 PST** —
always Wednesday night, never slipping into Thursday. One run at a time
(`concurrency`), 20-minute timeout, credentials written from a secret and deleted on
exit, run log kept as an artifact for 90 days even when the run fails. The Runs tab
is written in plain English. `workflow_dispatch` lets RISE trigger a run by hand.

**Block 4 complete.** Read-only dashboard (`dashboard/`) — status, cost against the
$20 ceiling, and run history, read via a Vercel serverless function so the Sheet can
stay unpublished. Builds clean; both states rendered in a real browser
(`evidence/screenshots/`). Never deployed, never read a real Sheet.

**`HANDOFF.md` written** (§13) — plain language, no developer required.

**All four blocks are done.** What remains is not code.

**Blocking:**
- `ANTHROPIC_API_KEY` is a **placeholder** (`.env.example`). Scoring cannot run until
  it is real, and §11 Q6 — who owns the key and the ~$2/month bill — is unanswered.
- `MIN_AWARD` is unset — the run uses a `$25,000` placeholder and says so every time.
  §11 Q1 is explicit that this must not be guessed.
- The calibration fixtures are **not Mauri's**. The harness runs; a pass proves the
  pipeline ranks, not that it is calibrated.

See `STAKEHOLDER.md`.

## Setting it up (one time)

Three repository secrets, under **Settings → Secrets and variables → Actions**:

| Secret | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | The API key. ~$2/month at current volume. |
| `RISE_SHEET_ID` | The id in the Sheet URL: `docs.google.com/spreadsheets/d/`**`<this>`**`/edit` |
| `GOOGLE_SHEETS_CREDENTIALS` | The whole service-account JSON, pasted in |

Then Mauri clicks **Share** on the Sheet and pastes in the service account's email.
That is her entire setup.

## Stopping it

Set `ENABLED` to `FALSE` in the Config tab of the Sheet. The next run exits before
making a single network call — verified with a socket guard, not just by reading the
code. No terminal, no repo, no phone call to anyone.

If the Sheet itself is unreachable, the scheduled run **refuses to run at all** rather
than falling back to defaults. Defaults would mean `ENABLED=True`, so an outage could
otherwise swallow her decision to turn it off.
