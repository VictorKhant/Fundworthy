# Rise-Fund-Finder

Weekly funding-opportunity agent for **RISE San Diego**, built at the AI Trailblazers
Social Impact Hack-AI-thon (San Diego, Aug 1–2 2026). RISE San Diego owns this work.

It watches the funders RISE already has relationships with and leaves a short, sourced,
ranked list of what is worth applying for — on a dashboard Mauri controls, and on a
Wednesday-night schedule if she wants one.

**The problem it solves is not "find more grants."** RISE's COO can already find them;
the problem is that most of what she finds is too small to justify a 10-hour
application. So this agent is built to return *few* results, and to say "amount not
stated" rather than guess. See `CLAUDE.md` §1.

## Run it

```bash
./start.sh              # everything: deps, dashboard build, app on localhost:8000
```

That is the whole thing. First run takes a minute to install; after that it is instant.

The pipeline on its own, if you want it without the UI:

```bash
.venv/bin/python -m agent.run --no-llm            # free tiers only, $0.00, no key
.venv/bin/python -m agent.run                     # + scoring; ~$0.18/run
.venv/bin/python -m agent.run --dry-run           # crawl and report, write nothing
.venv/bin/python -m agent.run --no-archive        # ignore monthly dedup, show repeats
.venv/bin/python -m agent.run --sink sheets       # export to a Google Sheet
.venv/bin/python -m pytest tests/ -q              # 126 tests, offline, no key needed
.venv/bin/python -m tests.calibration --dry-run   # the §10 test, filters only
```

## Where things are

| Path | What |
|---|---|
| `CLAUDE.md` | The spec. Read it first — including the v2 note at the top. |
| `docs/PLAN.md` | What v2 changed and why. Start here for the current shape. |
| `start.sh` | One command to run the whole thing |
| `app/main.py` | The REST API. Localhost only. |
| `app/db.py` | The SQLite store — settings, programs, funders, findings, runs |
| `app/secrets.py` | The API key: encrypted at rest, write-only, never returned |
| `app/assistant.py` | "Paste a link, get a program card" — so nobody writes a prompt |
| `app/runner.py` | The Re-run button. A subprocess, so Stop actually stops. |
| `agent/sources.py` | The shipped seed registry. The live list is in the database. |
| `agent/apis.py` | The two indexed lists — CA Grants Portal (CKAN) and Grants.gov |
| `agent/sd_funders.py` | The 44 researched funders. Every URL fetched and read. |
| `agent/irs990.py` | 990 lookup — what is reachable, and what is honestly not |
| `app/export.py` | Download the week as a spreadsheet |
| `agent/parse.py` | Page → candidate. The hard part. |
| `agent/filters.py` | The §7 hard rejects. Free — they run before any model call. |
| `agent/score.py` | Haiku triage → Sonnet scoring, behind a hard $1.00 ceiling |
| `agent/verify.py` | The accuracy gate. No verbatim quote on the page, no number. |
| `agent/discovery.py` | The seam for searching beyond the partner list |
| `dashboard/src/` | The React UI — sidebar, dashboard, archive, settings |
| `tests/calibration.py` | The §10 test. "The only test that matters." |
| `HANDOFF.md` | For RISE. Plain language, no developer required. |
| `docs/handoff/Fundworthy-guide-for-RISE.pdf` | The same thing as a printed guide, with screenshots. What Mauri actually gets. |
| `docs/DEPLOY-ORACLE.md` | Putting it on an Oracle free-tier VM, step by step |
| `STAKEHOLDER.md` | Open questions, answers, commitments |
| `evidence/` | What we ran, what broke, what we corrected |

## Status

**The pipeline works end to end, with a real key, against live funder pages.** That was
the biggest open question in this repo and it is closed:

| | |
|---|---|
| Sources searched | **60** — 44 researched SD/CA funders, 8 former partners, the CA Grants Portal and Grants.gov |
| Cost of one full run | **$0.60** against a $1.00 ceiling |
| Killed for $0.00 before any model call | **259 of 356** candidates |
| Repeat findings killed for $0.00 | 17 of 17 on a same-month re-run |
| Tests | **126**, all offline, no key required |

The **accuracy gate fired on live data**, and checking *why* turned up a real parser
bug: Prebys renders "Up to $150,000" with each digit group in its own element, so we
were extracting `$\n150\n,\n000`, finding no amount at all, and then discarding Sonnet's
*correct* reading of it. Fixed; records with a sourced award amount went **0 → 1** on
the same crawl. Full write-up in `evidence/README.md` E10–E14.

**The control surface is built** — award floor, deadline runway, result cap, spend
limit, sector selection, program cards with CRUD and an AI drafting assistant, an
editable funder list, a monthly archive, and a Re-run button that streams live output
and can actually be stopped.

**Answered since v1:** the award floor is **$10,000** (§11 Q1), **yes to government
RFPs and contracts** (§11 Q3), and — the big one — **§11 Q5, the forced-rank**:
program fit 40, award size 35, can-we-finish-in-time 25, and funder warmth deleted.

**The biggest change came from a stakeholder correction.** RISE does *not* want
opportunities from funders it already has relationships with — those cheques arrive
without reapplying. So warmth went from a +20 scoring boost to a reason to *exclude*,
and the partner list was replaced by **44 researched San Diego / California funders**,
every URL fetched and read before admission. See `evidence/README.md` E17.

**Still open, and honestly so:**
- **Mauri has not used it.** Everything above is a claim about a UI she has not touched.
- **No commitments secured.** `STAKEHOLDER.md`'s table is empty — 10 rubric points and
  the first tie-breaker.
- **Nothing is deployed**, and the GitHub Actions workflow has never executed.
- **The calibration fixtures are not Mauri's**, and were written against the old
  $25,000 floor. A pass proves the pipeline ranks, not that it is calibrated.
- **Score weights are still provisional** (§11 Q5), and the match-requirement filter
  (§11 Q4) is still flagged rather than enforced.
- **"Search beyond our partners" does nothing yet** — the seam is built, the provider
  is on a teammate's branch.

See `STAKEHOLDER.md` and `evidence/README.md` → "What is NOT evidenced yet".

## Setting it up

Run `./start.sh`, open the page, go to **Settings**, paste a Claude API key. That is it.
Everything else — the funder list, the programs, this month's findings — is already
there.

The key is encrypted on disk and no endpoint will ever return it; the page can only show
you the last four characters. Whoever's key it is pays the bill, which at this volume is
**a couple of dollars a month**.

Nothing is exposed to the internet. The app binds to localhost.

### The scheduled run (optional)

`.github/workflows/weekly.yml` still fires 06:00 UTC Thursday = **Wed 23:00 PDT / 22:00
PST** — always Wednesday night, never slipping into Thursday. It needs three repository
secrets (`ANTHROPIC_API_KEY`, `RISE_SHEET_ID`, `GOOGLE_SHEETS_CREDENTIALS`) and has
never been run. See `HANDOFF.md`.

## Stopping it

Untick **"The agent is switched on"** at the bottom of *This week's search*. Nothing
runs — no searching, no spending — until you turn it back on. No terminal, no repo, no
phone call to anyone.

For the scheduled run, the same switch applies, and if config cannot be read at all the
run **refuses to start** rather than falling back to defaults. Defaults would mean
"switched on", so an outage could otherwise swallow the decision to turn it off.
