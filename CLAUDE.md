# CLAUDE.md — RISE San Diego Funding Opportunity Agent

Working spec for Claude Code. Read this before writing any code in this repo.

Built at the AI Trailblazers Social Impact Hack-AI-thon, San Diego, Aug 1–2 2026.
The partner organization (RISE San Diego) owns this work.

---

## 1. The problem, in the stakeholder's own words

Mauri Hamilton is COO at RISE San Diego. She is responsible for finding funding.

What she told us:

- Searching for funding takes a **substantial, recurring block of her week**.
  (TODO: capture the real number from Mauri and put it here. An earlier draft of this
  file carried a specific figure that turned out not to be hers — it has been removed
  rather than left in, because a made-up stat about a real person is worse than a gap.)
- She reports findings at a **Thursday meeting**.
- The team will spend **no more than 10 collective hours** on any single application.
- All that searching **"doesn't guarantee the grants found are worth the application —
  mainly due to the low award amount."**

Read that last line carefully. The bottleneck is **not** discovery volume. It is that
discovery yields opportunities too small to justify a 10-hour application. An agent
that finds *more* grants makes her problem worse.

### Success metric

| | Today | Target |
|---|---|---|
| Hours spent searching | a recurring block of her week | ~0 |
| Hours spent reviewing | — | 1 / week (Thursday AM) |
| Opportunities surfaced | many, mostly too small | few, all above the award floor |
| Cost | COO time | < $20 / month |

If the agent surfaces six opportunities and all six clear the award floor, that is a
**successful run**. Do not treat a low count as failure.

---

## 2. The user

**Mauri Hamilton, COO.** Zero AI experience. This is the binding design constraint.

Hard rules:

- **Mauri never writes a prompt.** If any workflow requires her to phrase a request to
  an AI, that workflow is wrong. Her surface area is: type in a spreadsheet, read a
  page.
- **Mauri never sees a terminal, a repo, a config file, or an API key.**
- She works in **Google Sheets** by choice — shareable, multi-editor, familiar. Do not
  move her off it.
- She has a RISE Google account and can authorize sharing.

Secondary user: **Veronica Baker, Grant Writer.** The agent hands off to her. It does
not do her job (see Non-goals).

---

## 3. Non-goals — refuse these

Explicitly out of scope for v1. If you find yourself building one of these, stop.

- ❌ User accounts, login, or auth on the dashboard. v1 dashboard is **read-only** and
  link-shared. This removes the entire OAuth surface.
- ❌ Multi-tenant / other-org support. Preserve *optionality* via the adapter pattern
  (§6), build nothing more.
- ❌ Writing or submitting applications. The agent stops at a ranked, sourced list.
- ❌ Sending any email on RISE's behalf.
- ❌ Editing configuration in the dashboard. Config lives in a Sheets tab she already
  knows how to edit.
- ❌ Any unbounded loop. Every run has a hard cost ceiling and a hard stop.

---

## 4. Architecture

```
                     ┌──────────────────────────────┐
   Wed 11pm PT ─────▶│  GitHub Actions (cron)       │
                     │  reads config from Sheet     │
                     └──────────────┬───────────────┘
                                    │
                     ┌──────────────▼───────────────┐
                     │  agent/  (Python)            │
                     │  1. load source registry     │
                     │  2. fetch + parse            │
                     │  3. deterministic filters    │
                     │  4. cheap-model triage       │
                     │  5. strong-model scoring     │
                     │  6. emit Opportunity records │
                     └──────────────┬───────────────┘
                                    │
                     ┌──────────────▼───────────────┐
                     │  sinks/sheets.py             │
                     │  (service-account write)     │
                     └──────────────┬───────────────┘
                                    │
        ┌───────────────────────────▼────────────────────────────┐
        │  Google Sheet  — the product                            │
        │  ├── Opportunities   (agent appends; Mauri reviews)     │
        │  ├── Config          (Mauri edits; agent reads)         │
        │  ├── Org Profile     (boilerplate, edited rarely)       │
        │  ├── Funders         (warmth ratings, exclusions)       │
        │  └── Runs            (run log: cost, counts, stop reason)│
        └───────────────────────────┬────────────────────────────┘
                                    │ read-only
                     ┌──────────────▼───────────────┐
                     │  dashboard/ (static, Vercel) │
                     │  run history, cost, progress │
                     └──────────────────────────────┘
```

**Why this shape:**

- No server to maintain. GitHub Actions cron is free and versioned.
- No hosting bill. Vercel free tier for a static read-only page.
- The Sheet *is* the product. If every other piece dies, Mauri still has her data in a
  tool she owns and understands.
- Service account auth means Mauri's only setup step is clicking **Share** on the Sheet
  and pasting in an email address.

---

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Agent | **Python 3.11+** | Best parsing ecosystem; grant pages are the hard part |
| HTTP | `httpx` | async, timeouts, retries |
| Parsing | `selectolax` (fast) + `BeautifulSoup` (fallback) | |
| Dates | `dateparser` | funder deadline formats are chaotic |
| LLM | **Anthropic API** — Haiku for triage, Sonnet for final scoring | cost tiering, see §8 |
| Sheets | `gspread` + Google service account | no OAuth dance, no token refresh |
| Scheduler | **GitHub Actions** `schedule:` cron | free, versioned, no server |
| Secrets | GitHub Actions Secrets | never commit a key |
| Dashboard | **Vite + React**, static build on Vercel | read-only, no backend needed |
| Dashboard data | Vercel serverless fn reading the Sheet via service account | keeps the Sheet unpublished |

Not using a subscription plan for the pipeline — a headless scheduled job needs API
credits, not a chat seat. Expected real cost is a few dollars a month (see §8).

---

## 6. Data model

One normalized record. **The agent emits this; sinks render it.** Adding a non-Sheets
sink later means writing one file in `sinks/`, not touching the agent.

```python
@dataclass
class Opportunity:
    # identity
    id: str                      # stable hash of source_url + title
    title: str
    funder: str

    # the numbers that decide everything
    award_min: int | None
    award_max: int | None
    deadline: date | None
    estimated_effort_hours: int | None   # vs the 10-hour cap

    # matching
    program_match: list[str]     # ["RULFP", "RESILIENCE", "ARTS"]
    score: int                   # 0-100
    score_rationale: str         # one sentence, human-readable

    # trust — non-negotiable
    source_url: str              # REQUIRED. no URL, no record.
    verified: bool               # did we read the funder's own page?
    needs_human_check: bool      # ambiguous deadline/amount → flag, don't guess
    fetched_at: datetime
```

### Accuracy rules — these are not optional

- **Never state a deadline or an award amount that is not on a page we fetched.** If it
  can't be sourced, leave the field null and set `needs_human_check = True`.
- `source_url` must point at the funder's own page, not an aggregator summary.
- Judges include working funders. A wrong deadline in the demo is fatal.

---

## 7. Scoring

### Hard filters (reject before any LLM call — these are free)

```
REJECT if award_max < MIN_AWARD                    # ← TBD, see §11. The main filter.
REJECT if deadline is within 14 days               # can't do a 10-hr app well
REJECT if geography excludes San Diego County,
          Imperial County, California, or national
REJECT if funder is a religious organization       # Mauri, explicit
REJECT if funder is a political party              # Mauri, explicit
REJECT if funder == "County of San Diego Equity Impact Grant"   # done, no more funding
REJECT if requires a match RISE cannot meet        # ← TBD
```

Geography note: RISE operates across **San Diego AND Imperial Counties** (Far
South/Border North spans both). Do not hardcode San Diego County alone.

### Warm funders (score boost)

From the 2025 Impact Report, confirmed warm by Mauri:

San Diego Foundation · Alliance Healthcare Foundation · Prebys Foundation ·
City of San Diego Economic Development · City of San Diego Commission for Arts and
Culture · California Arts Council · The Morales Fund · The Villegas Fund

Also relevant as intermediaries/networks: Catalyst of San Diego & Imperial Counties,
USD Nonprofit Institute, Live Well San Diego, San Diego Regional Arts and Culture
Coalition.

### Three programs, three vocabularies

Do **not** run one search across all three. They live in different funder universes.

| Program | Funder-facing language | Funder type |
|---|---|---|
| **RISE Urban Leadership Fellows** | leadership pipeline, adaptive leadership, resident-led civic engagement, BIPOC leadership development, cohort fellowship, DEIA capacity building | leadership / equity / community foundations |
| **RISE Resilience & Renewal** | nonprofit leader burnout, whole-body leadership, somatic practice, polyvagal theory, wellness, workforce retention, health tech | **health & behavioral health funders** — this program was born out of Alliance Healthcare Foundation's i2 Challenge |
| **RISE Arts** | arts and social justice, artists from historically marginalized communities, creative placemaking, cultural equity, arts capacity building | public arts agencies (CAC, City Arts & Culture), arts foundations |

### Score composition (0–100)

Weights are **TBD until Mauri completes the forced-rank** (§11). Placeholder:

- Award size relative to floor — 35
- Program fit, weighted toward her three priorities — 25
- Funder warmth — 20
- Effort vs. the 10-hour cap — 15
- Deadline runway — 5

---

## 8. Cost control

Budget: **$20/month ceiling**, target actual spend under $6/month.

Weekly run budget: **$1.00 hard ceiling.** The run aborts and logs `stop_reason:
budget` if exceeded. No exceptions, no retries past the ceiling.

Tiering — the whole cost strategy:

1. **Free tier.** Fetch and parse. Deterministic filters (regex on dollar amounts,
   `dateparser` on deadlines, keyword geography match). Kills most candidates at zero
   LLM cost.
2. **Cheap tier.** Haiku triage on survivors only. Strip HTML to text first, cap at
   ~2k tokens per candidate. Binary relevant/not.
3. **Expensive tier.** Sonnet scoring + `score_rationale` on the top N only, where N is
   the cap from Config.

Never send a full HTML page to a model.

### Stop conditions

The run ends on the **first** of:

- `target_met` — cap reached
- `budget` — $1.00 spent
- `sources_exhausted` — registry fully crawled

Log which one fired. This is what the dashboard displays.

> **Design note — cap, not quota.** The stakeholder asked for "the agent won't stop
> until it finds the target number." We deliberately did not build that. A quota forces
> the agent to pad with low-value opportunities, which is exactly the problem she is
> hiring us to solve. Six good results is a good week. This decision is intentional and
> should be stated in the demo.

### Kill switch

Config tab, cell `ENABLED`. If `FALSE`, the Action exits immediately at step 0. Mauri
can stop the agent herself, from a spreadsheet, without calling anyone.

---

## 9. Schedule

- Agent runs **Wednesday 11:00 PM PT** via cron.
- Brief is sitting in the Sheet when Mauri opens it **Thursday morning**.
- She spends her **1 hour** reviewing before the Thursday meeting.

Size the output for one hour. That is roughly 8–15 opportunities with real depth, not
50 rows. Sort by score descending. Put `score_rationale` in a column she can read
without scrolling.

Config tab controls: `run_day`, `run_time`, `max_opportunities`, `min_award`,
`programs_active`, `ENABLED`. All plain-English, all editable by her, no technical
vocabulary anywhere on that tab.

---

## 10. Repo layout

```
rise-funding-agent/
├── CLAUDE.md                    ← this file
├── .github/workflows/weekly.yml ← cron trigger
├── agent/
│   ├── run.py                   ← entrypoint, orchestration, budget ceiling
│   ├── sources.py               ← the source registry (see §11 Q2)
│   ├── fetch.py                 ← httpx + retry + politeness delays
│   ├── parse.py                 ← page → raw candidate
│   ├── filters.py               ← deterministic rejects, zero LLM cost
│   ├── score.py                 ← tiered LLM scoring
│   └── models.py                ← Opportunity dataclass
├── sinks/
│   ├── base.py                  ← Sink protocol
│   └── sheets.py                ← the only implementation we ship
├── dashboard/                   ← Vite + React, read-only
├── tests/
│   └── calibration.py           ← Mauri's 5 yes / 5 no. MUST PASS.
└── HANDOFF.md                   ← written Sunday, for RISE
```

### Calibration test

`tests/calibration.py` holds five opportunities Mauri says are a clear yes and five she
says are a clear no. The scoring model must rank all five yeses above all five noes.

This is the only test that matters. Run it after every scoring change. Screenshot the
before/after when you correct the model — that screenshot is the strongest evidence of
human-AI collaboration you will produce all weekend.

---

## 11. Open questions — blocking

| # | Question | Blocks | Owner |
|---|---|---|---|
| 1 | **What is the smallest award worth 10 hours of team time?** | `MIN_AWARD`, the primary filter | Mauri |
| 2 | Does RISE have Candid / Foundation Directory / Instrumentl access? If not, which ~20 funder pages should we watch? | `sources.py` — the whole crawl scope | Mauri |
| 3 | Government contracts and RFPs too, or grants only? | doubles source scope (SAM.gov, County/City procurement) | Mauri |
| 4 | Can RISE meet a 1:1 match requirement? | hard filter | Mauri |
| 5 | Forced-rank: award size / win likelihood / program fit / funder warmth / low reporting burden | score weights §7 | Mauri |
| 6 | Who owns the Anthropic API key and this repo after Sunday? Name + payment method. | handoff, §12 | RISE |
| 7 | Annual operating budget and EIN | Org Profile tab; funders filter on these | Mauri |

Do not guess at #1. Everything downstream depends on it.

---

## 12. Build order — timeboxed

Hackathon reality: showcase is Sunday afternoon. Ship in this order and stop when the
clock says stop.

**Block 1 — Saturday night, 3 hrs. Must complete.**
Source registry (start with the 8 warm funders' own pages) → fetch → parse → normalized
record → append to Sheet. Run it once against real pages. **A Sheet with real, sourced
opportunities in it is a complete demo on its own.**

**Block 2 — Saturday night, 1 hr.**
Hard filters + scoring. Run `tests/calibration.py`. Fix until it passes.

**Block 3 — Sunday morning, 2 hrs.**
GitHub Actions cron. Cost ceiling. Runs tab. Kill switch.

**Block 4 — Sunday morning/midday, 3 hrs. Cut this first if behind.**
Read-only dashboard.

**HARD CUTOFF — Sunday 2:00 PM.** Freeze code. Write `HANDOFF.md`. Assemble the
evidence package. Rehearse the demo twice.

The rubric awards 10 points for what you built and 20 for stakeholder evidence and
commitments. Do not spend Sunday afternoon coding.

---

## 13. Handoff

`HANDOFF.md` must contain, in plain language:

- What the agent does, in three sentences.
- How to change what it looks for (→ the Config tab, with a screenshot).
- How to stop it (→ set `ENABLED` to `FALSE`).
- Who owns the API key and what it costs per month.
- What to do when it breaks, and whose name to call.

Sustainability question to answer honestly in the demo: **an unmaintained scheduled job
is a liability, not an asset.** Name who owns it. AI Trailblazers runs a paid
apprenticeship program that places people with nonprofits for exactly this kind of
ongoing maintenance — worth raising with Mauri as the 30-day answer.
