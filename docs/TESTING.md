# Test guide — is this actually working?

Copy-paste, in order. Steps 1–4 need **no API key and cost nothing**. Step 5 is the
first real spend (~$0.25). About 20 minutes end to end.

Branch: **`phyo-build`**. Every command runs from the repo root.

Legend: ✅ what a pass looks like · ⚠️ expected, not a bug · 🔎 what to actually look at

---

## 0. Get set up

```bash
cd ~/PROJECTS/Rise-Fund-Finder
git checkout phyo-build
git pull
```

You need Python 3.11+ and Node 18+. Nothing else.

---

## 1. Start it (~1 min first time, instant after)

```bash
./start.sh
```

✅ It prints `RISE Fund Finder → http://localhost:8000`. Open that in a browser.

🔎 **What you should see on the main dashboard:**
- **This week's search** — award floor showing **$10,000**, runway 14 days, cap 12,
  spend limit $1.00, four sector checkboxes ticked
- **Programs to find funding for** — 7 cards, 3 ticked (Arts, Resilience, RULFP)
- **Funders we watch** — **60**, most of them researched and URL-verified, each
  with a tick box, plus an empty **Remove list** below them
- A banner saying no API key is saved yet

⚠️ The findings list is empty on a fresh database. Correct — nothing has run.

Leave this running. Open a **second terminal** for everything below.

---

## 2. The test suite — offline, no key, ~1 second

```bash
.venv/bin/python -m pytest tests/ -q
```

✅ `126 passed`

🔎 **The four that matter most**, if you want to read one thing:

```bash
.venv/bin/python -m pytest tests/ -q -k "api_key_is_never_returned or plaintext or human_check_rows_sort_last or budget_is_customizable" -v
```

- `test_api_key_is_never_returned_by_any_endpoint` — sweeps every GET endpoint asserting
  the key does not appear. If this ever fails, the key is one screenshot from public.
- `test_key_is_not_stored_in_plaintext_on_disk` — greps the actual `.db` file.
- `test_human_check_rows_sort_last` — a 99-scoring row needing a human check still sorts
  below a clean 20. Mauri asked for that directly.
- `test_the_run_budget_is_customizable_end_to_end` — the ceiling she types on the
  dashboard is the ceiling the run refuses to spend past. Three hops, each of which has
  broken silently before.

---

## 3. A free run against real funder pages (~3 min, $0.00)

```bash
.venv/bin/python -m agent.run --no-llm
```

🔎 **Watch for, in order:**

```
Querying 2 indexed source(s)…
  ✓ State of California        46 of 173 active CA grants are on-mission
  ✓ U.S. Federal Government    12 federal opportunities with runway, from 67 hits
  ✓ Prebys Foundation          1 amounts, 0 deadlines, 8 links
  ✗ County of San Diego        ReadTimeout:
114 candidates survived the free filters.
```

✅ ~27 of 31 sources answer. ✅ `cost $0.0000`.
⚠️ County of San Diego times out most runs — their site is slow, not missing. It is
reported as `unreachable`, which is the point: a broken source never looks like a quiet
week.

🔎 **Scroll to `rejected before any model call`.** That block is the whole cost thesis —
~200 candidates killed for nothing, before a single model call.

### Now run it a second time. This is the dedup test.

```bash
.venv/bin/python -m agent.run --no-llm
```

✅ `0 candidates survived` and `already_seen_this_month` in the reject table.
✅ Still `$0.0000` — the repeat cost nothing because dedup runs in the free tier.
⚠️ **The dashboard does not go blank.** Refresh it — this month's findings are still
there. (That was a real bug, found by running exactly this test.)

To see repeats again: `.venv/bin/python -m agent.run --no-llm --no-archive`

---

## 4. The kill switch

On the dashboard, untick **"The agent is switched on"** → **Save these settings** →
press **Re-run search pipeline**.

✅ It refuses: *"The agent is switched off. Turn it back on in Settings first."*
✅ No network call is made.

Tick it back on before continuing.

---

## 5. The paid tiers — first real spend (~4 min, ~$0.25)

**On the dashboard → Settings**, paste a Claude API key, press **Save key**, then
**Check it works**.

✅ *"That key works."*
✅ The page shows only `sk-ant-…4f2a`. There is **no** way to make it show the rest —
that is deliberate, and step 2 has a test asserting it.

Back on the main page, press **Re-run search pipeline**.

🔎 **Watch the live log under the button.** Three things to look for:

```
  scored  65  City of San Diego Commission f  Apply for Funding …  ($0.02379)
  ⚠ geography_stated unverified (quote not on page) — dropping 'San Diego'
```

1. **No funder gets priority for being known.** RISE told us they do not want
   opportunities from funders they already receive money from, so warmth was removed
   from the score and the ordering entirely — it is now a reason to put a funder on the
   **Remove list** instead. Results are ranked on the opportunity alone.
2. **The ⚠ lines are the accuracy gate working.** A value the model reported, thrown
   away because the sentence backing it was not on the page. Do not treat those as
   failures — and do not treat them as wins either without checking the page. See
   `evidence/README.md` E12 for why that distinction cost us a real $150,000 grant.
3. **Cost lands around $0.60** against the $1.00 ceiling, and the run usually
   stops on `target_met` — the 12-result cap, not the budget.

✅ **Stop the search** genuinely stops it mid-run (it is a subprocess, not a thread).

🔎 **On the results:**
- Clean results first, **Needs your eyes** as its own block at the bottom.
- The big number on each card is **fit %** — the AI's own judgement, drawn dashed with
  an AI tag. The 0–100 **score** is what the list is ranked by and sits one row down.
- Values with a **dashed outline and an AI tag** are the model's judgement — fit, funder
  type, service areas, hours to apply, days to prepare, months to funds. Everything
  without that tag was read off the funder's own page or left blank.
- **Their 990** links to the actual IRS filing where we could identify the funder.
- A **Public database** chip marks anything from CA Grants Portal / Grants.gov.

⚠️ **"Needs your eyes" should be RARE — a handful, not most of the list.** It used to
fire on nearly everything, which made it meaningless; it now means one specific thing:
*the AI reported something it could not confirm against the page.* If most of a run
lands there, that is a real signal something has drifted — tell us.

⚠️ **Most results will say "amount not stated" or "deadline not stated", and that is
normal.** Most funders publish neither — we checked across 155 pages. The score already
accounts for it.

---

## 6. The card assistant (~30 sec, ~$0.015)

Programs → **ILIA** (or any empty card) → **Edit**. The link is already filled in.
Press **Read this page for me**.

✅ The card fills in: summary, what it funds, keywords, search queries, funder types.
✅ It reports what it could **not** find, and how useful it thought the page was.
✅ Nothing is saved until you press **Save**.

🔎 That flow is the answer to `CLAUDE.md` §2 — *"Mauri never writes a prompt."* She
corrects a draft about her own programme instead of composing an instruction she has no
basis to check.

### The empty-card warning

Tick **ILIA** *without* filling it in, then run:

```bash
.venv/bin/python -m agent.run --no-llm 2>&1 | grep "⚠"
```

✅ Two warnings, in plain language:

```
⚠ Nothing was searched for ILIA — that program card is still empty. Open it,
  press Edit, and paste the program's page to fill it in.
⚠ California was searched for ARTS, RESILIENCE, RULFP only. ILIA has no California
  funding category on file, so nothing was searched for it there…
```

🔎 This is the fix for the worst defect the branch merge produced: ticking a program
outside the original three used to make both databases search *everything*, silently.

---

## 7. Everything else worth clicking

| Try this | Should happen |
|---|---|
| Untick a funder | Drops out of the next search; the row stays (relationship preserved) |
| **Remove** a funder | Confirm dialog that steers you to unticking instead |
| Set a program's own award floor to 5000 | The crawl filters at $5,000, not $10,000 |
| Change the spend limit to 0.25 and re-run | The run stops itself and says *"Hit the spending limit"* |
| **Archived findings** in the sidebar | This month's results, grouped by month |
| Stop the server, refresh the page | *"Could not reach the app. Is it still running? Start it again with ./start.sh"* |

---

## What this guide does NOT prove

- **That Mauri can use it.** Nobody at RISE has opened it.
- **That the scores match her judgment.** The calibration fixtures are ours, not hers,
  and were written against the old $25,000 floor.

  ```bash
  .venv/bin/python -m tests.calibration --dry-run
  ```

  ✅ `5/10 killed by free filters; no YES wrongly filtered` — and it says on every run
  that a pass proves the pipeline ranks, not that it is calibrated.
- **That the public grant databases are worth their cost.** One scored run, 37
  candidates from them, **zero** survived relevance triage (`evidence/README.md` E15).
- **That the scheduled GitHub Actions run works.** Never executed, and it reads config
  from a different place than the dashboard — see the note at the top of `weekly.yml`.

---

## If something breaks

```bash
# Start clean — deletes settings, programs, funders, findings and the saved key
rm -rf data && ./start.sh

# See what the last run actually did
.venv/bin/python -c "
from app.db import session; from app import repo
with session() as c:
    r = repo.latest_run(c)
    print({k: r[k] for k in ('status','stop_reason','usd_spent','opportunities_scored')})
    for h in r['source_health']: print(' ', h['status'], h['funder'])
"
```
