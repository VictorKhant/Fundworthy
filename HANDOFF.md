# Handoff — RISE San Diego funding agent

For RISE San Diego. Written in plain language on purpose: nothing here needs a
developer to read. If a sentence in this file requires technical knowledge to act on,
that is a bug in the file — tell us.

---

## What it does

Every Wednesday night, it visits the websites of the funders RISE already has
relationships with and reads their grant pages. It throws out anything too small,
anything closing too soon, and anything RISE cannot apply for — before spending a
cent. What survives lands in your Google Sheet, sorted best-first, with a one-line
reason and a link to the funder's own page, ready for Thursday morning.

**What it deliberately does not do:** it does not try to find *more* grants. Finding
them was never the hard part — the problem is that most of what turns up is too small
to justify a 10-hour application. So this agent is built to return **few** results.
Six good ones is a good week. If it returns three, that is not a malfunction.

It also never writes an application, never emails anyone on RISE's behalf, and never
states a dollar amount or deadline it did not read on the funder's own page. When it
cannot find one, it says "not stated" instead of guessing.

---

## How to change what it looks for

**Everything is in the `Config` tab of the Sheet.** Type in a cell, save. That's it.
There is no app to open, no password, no settings screen anywhere else.

| Setting | What it does |
|---|---|
| `ENABLED` | `TRUE` or `FALSE`. See "How to stop it" below. |
| `MIN_AWARD` | **The most important setting.** The smallest award worth 10 hours of the team's time. Anything smaller is never shown to you. |
| `MAX_OPPORTUNITIES` | How many results to bring you each week. Sized for a one-hour review. |
| `PROGRAMS_ACTIVE` | Which programs to search for: `RULFP, RESILIENCE, ARTS`. Remove one to pause it. |
| `RUN_DAY` / `RUN_TIME` | When it goes looking. |

> ⚠️ **`MIN_AWARD` is currently a placeholder of $25,000, and that number is a guess.**
> Nobody has told us the real floor. Every run prints a warning saying so. Until Mauri
> sets it, the agent is filtering on a number we invented — which is exactly the
> decision this tool exists to get right. **This is the single highest-value thing
> anyone can do to improve it, and it takes thirty seconds.**

> 📸 *Screenshot to add here once the Sheet exists: the Config tab with `MIN_AWARD`
> and `ENABLED` visible. Not included because no Sheet has been created yet.*

Changes take effect on the next run. To apply one immediately, see "Running it by
hand" below.

---

## How to stop it

**Set `ENABLED` to `FALSE` in the `Config` tab.**

The next run reads that cell before it does anything else and exits without visiting a
single website. Nothing is deleted; your existing results stay. Set it back to `TRUE`
whenever you want it running again.

You do not need to call anyone, open a terminal, or have an account anywhere. Mauri
can stop this tool herself, from a spreadsheet, in five seconds.

If the Sheet itself is ever unreachable, the agent **refuses to run at all** rather
than assuming it should. That is deliberate: guessing "on" could ignore a decision you
made to turn it off.

---

## What it costs, and who owns it

| | |
|---|---|
| **Anthropic API (the AI)** | ~**$2/month** at current volume. Hard ceiling of $1.00 per weekly run, enforced in code — the run stops and logs why rather than overspending. |
| **GitHub Actions (the scheduler)** | Free |
| **Vercel (the dashboard)** | Free tier |
| **Google Sheets** | Free, on RISE's existing account |
| **Total** | **~$2/month**, against a $20/month ceiling |

> ⚠️ **Nobody owns the API key yet.** This is unresolved and it is the thing most
> likely to quietly kill the project. The key needs a named person and a payment
> method. Until then the agent cannot score anything — it will still fetch and filter,
> but every result comes back unscored.

Owner: `________________________`  ·  Payment method: `________________________`

---

## When it breaks

The `Runs` tab logs every run in plain English — when it ran, how long it took, how
much it cost, and how it ended. **If Thursday morning arrives and the Sheet has no new
rows, look there first.**

| What you see | What it means | What to do |
|---|---|---|
| No new row at all | The scheduled job did not run | Check GitHub → Actions tab for a red X |
| "You had turned it off" | `ENABLED` is `FALSE` | Set it to `TRUE` |
| "Hit the spending limit" | It stopped early to protect the budget | Normal. Results are still valid, just fewer. |
| "Checked every funder on the list" | Normal, healthy run | Nothing |
| "Something went wrong" | See the Notes column | If it repeats two weeks running, escalate |
| Rows appear but everything is unscored | The API key is missing or expired | Replace the `ANTHROPIC_API_KEY` secret |
| A funder shows "couldn't reach" repeatedly | They changed their website | Their URL needs updating in `agent/sources.py` |

**Nothing here is urgent.** A missed week costs one week of results. Do not let anyone
tell you this needs an emergency fix.

**Who to call:** `________________________`

### Running it by hand

GitHub → **Actions** → **Weekly funding run** → **Run workflow**. There are options to
do a trial run that writes nothing, or to run without the AI (free). Useful after
changing `MIN_AWARD`, or to demo it.

---

## Honest limitations

Things we know are wrong or unfinished. Read these before trusting a result.

1. **The scores have never been calibrated against Mauri's judgment.** §10 of the spec
   calls for five opportunities she considers a clear yes and five a clear no; the test
   for this exists and runs, but on **placeholder examples we wrote ourselves**. It
   proves the pipeline can rank. It does not prove it ranks the way she would.
   **Treat every score as a starting point for her judgment, not a substitute.**

2. **No tier-1 funder publishes a deadline we can read.** Across 28 pages, we extracted
   zero. We widened the search patterns and re-ran; still zero. Deadlines appear to
   live in PDFs, in application portals, or nowhere public. **Always confirm the
   deadline on the funder's page before committing to an application.**

3. **Most funder pages never state an award amount.** 21 of 23 results had none. Those
   appear in a separate, clearly-labeled block below the ranked list — visible, but not
   ranked, because there is no number to rank them by.

4. **The Morales Fund and The Villegas Fund are not being watched.** Neither appears to
   have a public grants page. If they are relationship-only, they belong on the
   `Funders` tab as warmth records rather than in the crawl list. Someone should confirm.

5. **Two warm funders mention matching requirements** (Prebys Arts Ecosystem, CA Arts
   Council). We do not know what match RISE can meet, so the agent flags them and
   passes them through rather than filtering. Answering that question would tighten the
   list.

6. **It only watches eight funders.** Widening to intermediaries or government RFPs is
   a config change, not new code — but nobody has said whether that is wanted.

---

## The 30-day question

**An unmaintained scheduled job is a liability, not an asset.**

This thing will run every Wednesday whether or not anyone is watching. If a funder
redesigns their website in November and nobody notices, it will keep reporting
"couldn't reach" into an empty room — and the failure mode is silence, which is the
worst kind. It needs an owner, not a maintainer: someone who glances at the `Runs`
tab once a month.

AI Trailblazers runs a **paid apprenticeship program** that places people with
nonprofits for exactly this kind of ongoing maintenance. That is the realistic 30-day
answer, and it is worth raising with Mauri directly rather than hoping the team
absorbs it.

### First 30 days, in priority order

| # | Action | Owner | Why it matters |
|---|---|---|---|
| 1 | Mauri sets the real `MIN_AWARD` | Mauri | The whole product filters on this. It is currently a guess. |
| 2 | Name an API key owner + payment method | RISE | Without it, nothing gets scored |
| 3 | Mauri supplies 5 clear-yes / 5 clear-no grants | Mauri | Makes the scores trustworthy instead of plausible |
| 4 | Create the Sheet, share it with the service account | RISE | The agent has never written to a real Sheet |
| 5 | Watch four consecutive Thursdays | Mauri | Four weeks tells you whether it saves real hours |
| 6 | Decide: keep, widen, or switch off | Mauri | An honest kill decision beats quiet decay |

### What "working" looks like in four weeks

Mauri opens the Sheet Thursday morning, spends under an hour, and finds at least one
opportunity worth an application she would not otherwise have seen. If that is not
happening by week four, the answer is to change `MIN_AWARD` or turn it off — not to
add features.

---

## For whoever picks up the code

Start with `CLAUDE.md` — the full spec and the reasoning behind every decision. Then
`evidence/README.md`, which records what we tested, what broke, and what we corrected,
including the bugs we shipped and caught. `STAKEHOLDER.md` tracks the open questions.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m agent.run --no-llm --dry-run   # free, no key, writes nothing
.venv/bin/python -m tests.calibration --dry-run    # the test that matters most
```

Three GitHub repository secrets make it live: `ANTHROPIC_API_KEY`, `RISE_SHEET_ID`,
`GOOGLE_SHEETS_CREDENTIALS`. Then Mauri clicks **Share** on the Sheet and pastes in the
service account's email address. That is her entire setup.

**The one rule that is not negotiable:** never let the agent state a deadline or a
dollar amount that is not on a page it actually fetched. Funders read this output. A
wrong deadline costs RISE credibility that is far more expensive than a missed grant.
