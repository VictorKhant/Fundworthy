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

---

## What is NOT evidenced yet

Stated plainly, because claiming otherwise is the failure mode the rubric penalizes:

- ❌ **No stakeholder conversation logged since intake.** `STAKEHOLDER.md` shows 7 of 8
  blocking questions unanswered.
- ❌ **No commitments secured.** That table is empty. 10 points and the first tie-breaker.
- ❌ **Nothing written to a real Google Sheet.** The Sheets sink is built, the Config
  tab auto-creates, and the Runs row was verified against a stub worksheet (11 cells,
  headers aligned, plain-English stop reasons). But **no Sheet has been shared with a
  service account**, so the sink has never talked to Google.
- ❌ **The workflow has never executed.** `.github/workflows/weekly.yml` is validated
  as YAML — triggers, cron, concurrency, timeout, 7 steps, both `always()` guards —
  and the cron arithmetic is checked. It has **not run on GitHub**: the three required
  secrets do not exist yet, and `ANTHROPIC_API_KEY` is a placeholder.
- ❌ **The dashboard has never been deployed, and has never read a real Sheet.** It
  builds, both states render in a browser, and the API handler's edge cases are
  tested — but the data path to Google is unexercised.
- ❌ **The LLM tiers have never run.** `ANTHROPIC_API_KEY` is not set in this
  environment, so Haiku triage and Sonnet scoring are **written and statically checked
  but never executed against the real API.** Verified statically: model IDs, schemas
  (all-required, `additionalProperties: false`), no `temperature`/`top_p`/`top_k`/
  `budget_tokens` (removed/deprecated on Sonnet 4.6), `max_tokens` headroom for adaptive thinking.
  Not verified: that a real call returns what the schema promises. **Treat every score
  in this repo as unproven until someone runs it with a key.**
- ❌ **Calibration fixtures are not Mauri's.** The harness is real and runs; the ten
  fixtures are placeholders derived from CLAUDE.md §1 and §7. `tests/calibration.py`
  says so on every run and refuses to claim calibration. Blocked on question 8.
- ❌ **Score weights are provisional.** §7's 35/25/20/15/5 split is explicitly marked
  TBD pending Mauri's forced-rank (§11 Q5). They are in the scoring prompt as stated,
  labeled PROVISIONAL.
- ❌ **Prompt caching is off.** The scoring system prompt is ~554 tokens, below
  Sonnet 4.6's 2048-token cache minimum, so `cache_control` would be silently ignored.
  The code checks the threshold and only attaches the marker when it would do
  something; it turns on by itself once the Org Profile boilerplate lands.

---

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Free tiers only — fetch, parse, deterministic filters. $0.00, no key needed.
.venv/bin/python -m agent.run --no-llm --sink jsonl --out evidence/runs
.venv/bin/python -m tests.calibration --dry-run

# Full pipeline including scoring. Needs ANTHROPIC_API_KEY. ~$0.42/run.
.venv/bin/python -m agent.run --sink jsonl --out evidence/runs
.venv/bin/python -m tests.calibration
```

The `--no-llm` and `--dry-run` paths are the ones actually exercised in this repo.
The scoring paths are written but unrun — see "What is NOT evidenced yet" above.
