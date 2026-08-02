# Evidence package

Rubric: **Experiments run (10)** + **Evidence package (5)**, and it backs the
**Evidence-based claims (3)** in Presentation. The rule from the rubric's closing line:
*"A polished presentation without real experiments should not outscore a messy but
evidence-rich project."* So this directory is the messy, evidence-rich part.

Every run leaves an artifact here. Nothing in the demo gets claimed without a file.

```
evidence/
├── runs/         raw output + JSONL from actual runs against live funder pages
├── screenshots/  dashboard states, captured in a real browser
└── README.md
```

---

## Experiment log

### E1 — Can we get real, sourced opportunities out of the 8 warm funders?
**When:** 2026-08-01, Block 1
**Assumption tested:** the warm funders in §7 publish grant information on pages we can
fetch and parse without an aggregator subscription.
**Method:** crawl tier 1, follow one level of same-domain grant links, parse, emit records.
**Result:** 6/6 sources fetched, 28 pages parsed, 23 records with a live `source_url`.
Cost **$0.00** — no LLM calls in Block 1.
**Artifact:** `runs/block1-first-real-run.txt`, `runs/opportunities-*.jsonl`
**Verdict:** ✅ Confirmed. No paid data source is required to reach the warm funders.

### E2 — Are our funder URLs actually right?
**Assumption tested:** we can guess a funder's grants page from its domain.
**Result:** ❌ **Falsified.** 2 of 8 tier-1 URLs 404'd on the first run — San Diego
Foundation (`/nonprofits/grants/`) and Alliance Healthcare Foundation (`/grants/`).
Corrected to `sdfoundation.org/nonprofits/apply-for-a-grant/` and
`alliancehf.org/innovation-initiative-i2/` — the latter being the i2 Challenge that §7
says RISE Resilience & Renewal was born out of, so the guess had missed the single most
relevant page in the registry.
**Consequence:** `sources.py` now carries an explicit `Confidence` level per entry, and
`UNCONFIRMED` entries are never fetched — they surface in the run report as research to
do rather than failing quietly.

### E3 — Does naive dollar-amount extraction produce trustworthy award figures?
**Assumption tested:** the min and max dollar figures on a grants page approximate the
award range.
**Result:** ❌ **Falsified, and it mattered.** The run reported
`$440,000–$4,500,000` for the Alliance Healthcare i2 Challenge and
`$250,000–$3,000,000` for the California Arts Council FAQ. **Neither number was an award
size** — they were total program budgets and cumulative grants-awarded-since-inception.
Grants pages are full of dollar figures that are not awards: endowment size, annual
giving, revenue floors, historical totals.

This is the exact failure §6 forbids: *"Never state a deadline or an award amount that
is not on a page we fetched"* and *"Judges include working funders. A wrong deadline in
the demo is fatal."*

**Fix:** an amount is now extracted only when its own sentence presents it as a
per-award figure (`up to $X`, `awards range from`, `per grantee`), and never when the
sentence is about totals or history. Amounts found dropped **6 → 2**.

**Before / after — this is the human-AI correction, and it is the most important
artifact in this directory:**

| | Before | After |
|---|---|---|
| Records with an award amount | 6 | 2 |
| AHF i2 | `$440,000–$4,500,000` ❌ fabricated range | *amount not stated* ✅ honest |
| CA Arts Council FAQ | `$250,000–$3,000,000` ❌ program totals | *amount not stated* ✅ honest |
| Prebys Explore Grants | `$250,000–$1,300,000` ❌ | `$250,000` ✅ verified |

Verified against source text — Prebys reads: *"Two-year, general operating support of
up to $250K/yr to high-performing, culturally competent community health clinics."*

**The count went down and the output got better.** That is the whole thesis of this
project restated at the parser level: fewer, truer results beat more results.

### E4 — Do tier-1 funders publish machine-readable deadlines?
**Result:** ❌ **Zero deadlines extracted across 28 pages.** They appear to live in
PDFs, in application portals, or nowhere on the public page.

**Re-tested in E6 with a much wider cue set — still zero.** That rules out "my regex
was too narrow" and makes this a finding about the funders, not about our parser. It
threatens the "reject if deadline within 14 days" filter (§7) and the deadline column.
**Open with Mauri** — see `STAKEHOLDER.md`, new question 2.

### E5 — Can the free tier carry the filtering load, or do we need to pay per candidate?
**When:** 2026-08-01, Block 2
**Assumption tested:** the §7 hard filters are strong enough to make the LLM tiers
cheap, i.e. most junk dies at zero cost.
**Result:** ✅ Confirmed. On the live crawl, deterministic filters rejected **11 of 28**
parsed pages for **$0.00** — 6 as not-a-funding-opportunity (panelist calls, grantee
databases, volunteer listings) and 5 as thin landing pages.

On the calibration fixtures the free tier is stronger still: **5 of 5 clear NOs
rejected before any model call, with 0 of 5 clear YESes wrongly killed.** Every NO was
caught for free — below-floor award, religious funder, wrong geography, deadline
inside the 14-day runway, and a panelist call.

Projected weekly spend (17 Haiku triage + 12 Sonnet scores): **$0.42/run ≈ $1.81/month**
— against §8's <$6/month target and $20 ceiling. The `Budget` ceiling was tested
directly and refuses the call that would breach $1.00 rather than discovering the
overspend afterward.
**Artifact:** `runs/block2-filters-run.txt`

### E6 — Does a wider deadline cue set find deadlines the first parser missed?
**Assumption tested:** E4's zero-deadline result was a too-narrow regex, not a real
property of the pages.
**How it surfaced:** the calibration harness caught it, not the crawl. A fixture
reading *"Applications must be submitted by <date 5 days out>"* **passed the 14-day
runway filter** — the cue list had `submit by`, which does not match `submitted by`.
A too-soon grant would have reached Mauri looking like it had runway. Fixed by
widening the cue set (`postmarked by`, `no later than`, `closing date`,
`nominations due`, `applications must be`, …).

**Result on fixtures:** ✅ the 5-day deadline is now correctly rejected — 5/5 NOs caught.
**Result on live pages:** ❌ **still zero deadlines across 28 pages.** E4 stands.

The two halves matter separately: the fix was real and caught a genuine defect, *and*
it did not change the live finding. That is the difference between "our parser was
weak" and "these funders don't publish deadlines" — we can now say it is the second.

### E7 — Is the kill switch actually a kill switch?
**When:** 2026-08-01, Block 3
**Assumption tested:** §8's claim that setting `ENABLED=FALSE` makes the Action "exit
immediately at step 0."
**Method:** monkeypatched `socket.socket.connect` to raise on any outbound
connection, then ran the full entrypoint with `enabled=False`.
**Result:** ✅ Exit 0, zero sockets opened. The switch fires before any network call —
verified by instrumentation, not by reading the code.

**But testing it surfaced a hole worth more than the test.** `load_config` fell back
to shipped defaults whenever the Sheet was unreachable — and the shipped default is
`enabled=True`. So Mauri sets `ENABLED` to `FALSE`, a transient Sheets outage swallows
it, and the agent runs anyway: **the exact failure the kill switch exists to prevent.**

Fixed with a strict mode (`RISE_STRICT_CONFIG=1`, set in the workflow): if the Config
tab cannot be read, the run **refuses to start** and exits 1. Locally, without
credentials, the old permissive fallback still applies so the agent stays runnable.
Verified: strict + no credentials → exit 1; non-strict → exit 0.

### E8 — Does the cron actually land on Wednesday night in both DST regimes?
**Assumption tested:** a single UTC cron can satisfy §9's "Wednesday 11:00 PM PT"
year-round. GitHub Actions cron is UTC and does not observe daylight saving.
**Result:** ⚠️ Partially — no single expression is exact year-round, so we chose which
way to be wrong. `0 6 * * 4` resolves to **Wed 23:00 PDT** and **Wed 22:00 PST**.
The rejected alternative, `0 7 * * 4`, gives Wed 23:00 PST but **Thu 00:00 PDT** —
tipping past midnight into Thursday for eight months of the year.
Early is harmless; late risks her Thursday morning. Documented in the workflow.

### E9 — Does the dashboard work before the Sheet exists?
**When:** 2026-08-01, Block 4
**Assumption tested:** the read-only dashboard degrades honestly when there is no
Sheet to read — which is the actual current state, and will be RISE's state on first
deploy.
**Result:** ✅ Confirmed. Unconfigured returns a clean `200` with `configured: false`
and an instruction, not an error or a blank page. `POST` → `405` (read-only by
construction). Malformed credentials → `502` with a generic message; the credential
and stack stay server-side.
**Artifact:** `screenshots/dashboard-not-connected.jpg` — the real current state.

**Layout verified separately with fixtures.** To check the populated table, stat
tiles, and cost bar, the dev middleware was temporarily stubbed with sample rows,
screenshotted, and **reverted** (verified: zero fixture strings remain in
`vite.config.js`, and the endpoint returns `configured: false` again). That screenshot
is `screenshots/dashboard-layout-with-fixtures.jpg` — it proves the layout renders and
the `MIN_AWARD` placeholder warning surfaces. **It is not a real run.**

The check earned its keep: the "Last run" timestamp wrapped onto two lines at the
default stat size. Fixed with a `compact` variant.

### E10 — Does the paid tier actually work? (the big one)
**When:** 2026-08-02
**Assumption tested:** everything above E9 was written and statically checked but had
**never executed against the real API**. This file said so in bold: *"treat every score
in this repo as unproven until someone runs it with a key."*
**Method:** full pipeline against live funder pages with a real `ANTHROPIC_API_KEY` —
crawl → deterministic filters → Haiku triage → Sonnet scoring.
**Result:** ✅ **It runs.** 28 pages parsed, 17 survived the free filters, Haiku killed
11 more as not-an-opportunity, Sonnet scored 6.

| | |
|---|---|
| Cost, one full run | **$0.2056** |
| §8 per-run ceiling | $1.00 — used 21% of it |
| Projected monthly | ~$0.88, against a <$6 target and a $20 ceiling |
| Killed for $0.00 before any model call | 22 of 28 |

**Artifact:** `runs/block5-first-real-llm-run.txt`
**What this closes:** the single largest gap in this package. Every score in the repo
was previously hypothetical.

### E11 — Does the accuracy gate catch a real confabulation, or only a fixture?
**Assumption tested:** `agent/verify.py` passes 13 unit tests against hand-written
inputs. Unit tests prove the function works; they do not prove the failure it guards
against ever happens.
**Result:** ✅ **It fired three times on the first real run**, unprompted:

```
⚠ award unverified (quote not on page) — nulling None/250000
⚠ award unverified (quote not on page) — nulling None/150000
⚠ geography_stated unverified (quote not on page) — dropping 'San Diego'
```

Two award amounts and a geography were reported by the model and **thrown away** before
they could reach Mauri, because the verbatim sentence backing them was not on the page
we fetched. §6 calls a wrong number in the demo fatal; this is the mechanism that
prevents it, working on live data rather than in a test.

### E12 — Were those actually confabulations? (they were not, and that mattered more)
**How it surfaced:** E11 looked like a clean win, so we went and checked the pages
rather than claiming it. **We were wrong about what happened.**

The Prebys *2026 Rooted and Rising* page really does say **"Anticipated Grant Awards: Up
to $150,000"**. But each digit group sits in its own HTML element, so the text we
extract reads:

```
Up to $\n150\n,\n000
```

So the model was **right** and our parser was wrong — and the damage went two ways:

- the **free tier** found no award amount on the page at all, because the money regex
  cannot match across those newlines;
- the **gate** then discarded Sonnet's correct $150,000 because its quote could not be a
  literal substring of our own mangled text.

The gate was not wrong to fire — it failed in the safe direction, showing *"amount not
stated"* rather than an unconfirmable number. But a gate that discards *true* values is
still costing RISE opportunities, and "our parser mangled the page" is a bad reason to
drop a $150,000 grant.

**Fix:** repair split figures at source (anchored to `$`, so the rewrite can only touch
the inside of a money amount) plus a whitespace-insensitive second pass in the gate that
forgives **layout only** — every other character must still appear in order.

**Before / after, same crawl, same funders:**

| | Before | After |
|---|---|---|
| Records with a sourced award amount | **0** | **1** |
| Prebys *Rooted and Rising* | *amount not stated* | **$150,000, verified** |
| Run cost | $0.2056 | $0.1824 |

**Artifacts:** `runs/block5-first-real-llm-run.txt`, `runs/block5-after-split-amount-fix.txt`

Four regression tests added, including one asserting that a fabricated `$500,000` quote
is *still* rejected against the same repaired page — the fix must not launder a
hallucination on its way to fixing a layout bug.

**This is the most useful thing in this directory.** Not because the bug was hard, but
because the sequence was: run it for real → believe the win → go and check → find the
opposite of what we assumed → fix the actual defect → prove the guard still holds.

### E13 — Does the monthly archive stop Mauri re-reading the same grant?
**Assumption tested:** dedup keyed on `stable_id` in the free tier kills repeats before
they cost anything.
**Result:** ✅ A second run over the same funders in the same month rejected
**17 of 17 candidates** as `already_seen_this_month` for **$0.00**, and surfaced nothing.

That also exposed a bug worth more than the test: `run.json` was being written with only
*that run's* output, so a re-run mid-week **blanked the page** that should still have
shown everything found so far this month. Fixed — the file now carries the month's
findings while the run block still reports the run honestly.

### E14 — Can the card assistant replace Mauri writing a prompt?
**Assumption tested:** CLAUDE.md §2 forbids any workflow where she has to phrase a
request to an AI. A blank "describe this program in funder-facing language" box is
exactly that. Can pasting a link do the job instead?
**Method:** `POST /api/programs/draft` with `risesandiego.org/programs/ilia` — a program
we deliberately shipped as an **empty** card rather than inventing a description for.
**Result:** ✅ Returned a complete, sourced draft for **$0.014**: name, summary, what it
funds, 10 funder-facing keywords, 5 search queries, funder types.

Most importantly it reported its own limits without being asked:

> `page_confidence: 62`
> `fields_missing: ["program budget or funding goal", "sponsorship tiers and benefits",
> "geographic focus beyond San Diego (e.g., Imperial County)", "501c3 fiscal details",
> "attendance/reach metrics"]`

So the draft arrives with its caveats attached instead of looking uniformly confident,
and the card stays marked `AI draft — unreviewed` until a human saves it.

---

## What is NOT evidenced yet

Stated plainly, because claiming otherwise is the failure mode the rubric penalizes:

- ❌ **No stakeholder conversation logged since intake.** `STAKEHOLDER.md` now shows
  **10** open questions, three of which came out of this build rather than speculation
  (the four sectors, the real time-spent figure, and the fact that risesandiego.org
  lists **ten** programs where we were told seven).
- ❌ **No commitments secured.** That table is empty. 10 points and the first tie-breaker.
- ❌ **Nothing written to a real Google Sheet.** The Sheets sink is built and the Runs
  row was verified against a stub worksheet, but **no Sheet has been shared with a
  service account**, so it has never talked to Google. Note this matters less than it
  did: the Sheet is now an *export* target, not the product (docs/PLAN.md §0).
- ❌ **The GitHub Actions workflow has never executed, and v2 opened a gap in it.** The
  scheduled run reads config from the Google Sheet; the dashboard reads it from
  `data/rise.db`, which is gitignored (it holds the encrypted key). **Neither can see
  the other's settings**, so a floor Mauri changes on the dashboard would not change
  what the cron does. Documented at the top of `weekly.yml` with three ways out. The
  workflow stays off until one is chosen — two agents with two different ideas of what
  she wants is worse than one agent she has to press a button for.
- ❌ **Nothing is deployed.** The app runs locally by design (docs/PLAN.md §1) and has
  only ever run on a developer laptop. **Mauri has not used it herself.** Everything
  below about her workflow is a claim about a UI she has not yet touched.
- ❌ **Calibration fixtures are not Mauri's.** The harness is real and runs; the ten
  fixtures are placeholders derived from CLAUDE.md §1 and §7. `tests/calibration.py`
  says so on every run and refuses to claim calibration. Blocked on question 8. The
  fixtures were also written against the old $25,000 placeholder floor and have **not**
  been re-checked against the real $10,000 one.
- ❌ **Score weights are provisional.** §7's 35/25/20/15/5 split is still marked TBD
  pending Mauri's forced-rank (§11 Q5), and is in the scoring prompt labelled PROVISIONAL.
- ❌ **The "search beyond our partners" checkbox does nothing yet.** `agent/discovery.py`
  is the interface and a null provider; the implementation is on a teammate's branch.
  A run with it ticked reports `provider=none` rather than pretending.
- ❌ **`form_990_available` is never populated.** The column exists and is always `None`.
  Nothing has checked, and `None` means unknown — not "no".
- ⚠️ **Deadline enforcement is only as good as the deadline.** The first scored run
  surfaced a Prebys program whose deadline had passed; Sonnet said so in the rationale,
  but the date failed the quote gate, so `deadline` was `None` and the post-scoring
  "reject if passed" guard never fired. It scored 15 and is flagged for a human, which
  is the safe outcome — but a closed grant still reached the list. **Open item.**
- ⚠️ **Prompt caching is still effectively off.** The scoring prompt is now generated
  from the program cards and runs ~1,130 characters — still under Sonnet 4.6's
  2048-token cache minimum, so the marker is deliberately not attached. It turns on by
  itself as Mauri fills in more cards.

---

## Reproducing

```bash
./start.sh                                        # the whole app on localhost:8000

# or, the pipeline on its own:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python -m pytest tests/ -q              # 66 tests, offline, no key
.venv/bin/python -m agent.run --no-llm            # free tiers only, $0.00
.venv/bin/python -m tests.calibration --dry-run   # the §10 test, filters only

# Full pipeline including scoring. Needs a key. ~$0.18/run.
.venv/bin/python -m agent.run
```

Every path above has now been run for real. The scored runs in `runs/block5-*.txt` were
produced by the commands here, against live funder pages, with a real key.
