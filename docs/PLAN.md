# Implementation plan — v2 (human-in-the-loop control surface)

Written Sun Aug 2 2026, after merging `origin/main` into `phyo-build`.
Supersedes nothing in `CLAUDE.md` silently — every reversal is recorded in §0 below and
mirrored into `docs/DECISIONS.md`.

---

## §0 — Reversals of CLAUDE.md, and why

`CLAUDE.md` was written before Mauri's follow-up. Four of its rules are now wrong. They
are reversed deliberately, by the stakeholder-facing owner of this repo, not drifted
into.

| CLAUDE.md said | Now | Why |
|---|---|---|
| §3 "❌ Editing configuration in the dashboard" | **Reversed.** Config lives in the dashboard, backed by SQLite. | She asked for a customization surface. A spreadsheet cell cannot express "tick these three programs, with these search terms, at this floor." |
| §4 "The Sheet *is* the product" | **Demoted.** The dashboard is the product; the Sheet becomes an **export** target for the shortlist she keeps. | Same reason. `sinks/sheets.py` survives unchanged as an export path, so "she still owns her data in a tool she understands" survives too. |
| §5 "No server to maintain" | **Reversed.** A local FastAPI backend. | An API-key settings page, CRUD, a SQLite archive, a re-run button and a Sonnet card assistant are all impossible on a static site. |
| §1 "~16 hours a week searching" | **Deleted everywhere.** | The stakeholder-facing owner says the number is not true. We do not ship an unverified stat about a real person. Replaced with the part that *is* sourced — the 10-hour application cap and the low-award-amount pain — and a TODO to capture the real number. |
| §11 Q1 "Do not guess at MIN_AWARD" | **Answered: $10,000.** | Confirmed by the stakeholder-facing owner. The placeholder machinery comes out. |

Unchanged and still binding: §6 accuracy rules (no URL → no record; never state an
unsourced number), §8 cost ceilings and the kill switch, §7's reject list.

---

## §1 — Target architecture

```
Rise-Fund-Finder/
├── start.sh                    ← one command: build UI, run API, open browser
├── app/                        ← NEW — FastAPI backend
│   ├── main.py                 REST API + serves dashboard/dist
│   ├── db.py                   SQLite schema, migrations, connection
│   ├── schemas.py              Pydantic request/response models
│   ├── secrets.py              API-key storage — encrypted at rest, write-only
│   ├── repo.py                 CRUD for programs / funders / settings
│   ├── archive.py              month-keyed dedup + monthly purge
│   ├── runner.py               background pipeline execution + live status
│   └── assistant.py            Sonnet 4.6 "build a program card from a link"
├── agent/                      ← existing pipeline, mostly untouched
│   ├── config.py               ← now loads from SQLite (Sheet reader kept as fallback)
│   ├── sources.py              ← + sector tag; funder list now seeded into SQLite
│   ├── discovery.py            ← NEW — DiscoveryProvider seam (null impl for now)
│   └── fetch/parse/filters/score/verify/models
├── sinks/
│   ├── sqlite.py               ← NEW — primary sink
│   ├── webjson.py              kept (static export + the GitHub Actions path)
│   └── sheets.py               kept — now an *export* target, not the product
├── dashboard/src/
│   ├── App.jsx                 shell + sidebar router
│   ├── pages/{Dashboard,Archive,Settings}.jsx
│   └── components/…
├── data/rise.db                ← SQLite. gitignored.
└── tests/
```

**Deployment path is deliberately deferred.** The same FastAPI app runs on Render/Fly
with one env var change. Building local-first means the demo cannot be broken by a cold
start, and nothing about the code has to change to host it later.

### Merge safety for the teammate's discovery branch

He is building outside-the-warm-list discovery (curated registry + Claude web search) on
his own branch. To keep that merge cheap:

- `agent/sources.py` keeps its existing module-level lists **in place** — no
  restructuring, no moved entries.
- New behaviour goes in a **new** file, `agent/discovery.py`, exposing a
  `DiscoveryProvider` protocol with a `NullDiscovery` default. His implementation becomes
  one more provider; the dashboard's "search beyond our partners" checkbox lights it up.
- No conflict surface in `fetch.py`, `parse.py`, `filters.py`.

---

## §2 — Data model

### 2a. The eleven attributes Mauri asked for

Added to `Opportunity`, on top of the existing `id` / `found_on` / AI rationale:

| Field | Type | How it is filled | Sourced or inferred |
|---|---|---|---|
| `funder` | str | already have | sourced |
| `funder_type` | private_foundation / corporate / community / government / other | Sonnet | **inferred** |
| `service_areas` | list[str] | Sonnet — STEM, Arts, Youth, Equity, … | **inferred** |
| `geography` | str \| None | Sonnet, quote-gated | sourced |
| `award_typical` | int \| None | Sonnet, quote-gated | sourced |
| `award_min` / `award_max` | int \| None | already have, quote-gated | sourced |
| `deadline` | date \| None | already have, quote-gated | sourced |
| `deadline_type` | fixed / rolling / unknown | Sonnet, quote-gated | sourced |
| `form_990_available` | bool \| None | deterministic lookup on the funder name, else null | sourced |
| `confidence_pct` | int \| None | Sonnet — its own confidence this funder would fund RISE | **inferred, labelled** |
| `contact_note` | str \| None | Sonnet, quote-gated (a name/email must be on the page) | sourced |
| `source_url` | str | already have | sourced |

**The §6 accuracy rule is extended, not weakened.** Every *sourced* field keeps the
existing verbatim-quote gate in `agent/verify.py` — the model must return the sentence it
read the value from, and that sentence must be a literal substring of the fetched page, or
the value is nulled and `needs_human_check` is set. Every *inferred* field is rendered in
the UI with a visible "AI judgement" marker so it can never be mistaken for a fact off the
funder's page. `confidence_pct` in particular is a model opinion and is labelled as one.

### 2b. SQLite schema

```sql
settings(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)
-- min_award(=10000) · min_deadline_runway_days(=14) · max_opportunities(=12)
-- run_budget_usd(=1.00) · enabled(=1) · sectors_active(json) · anthropic_api_key(enc)

programs(id TEXT PK, name, slug UNIQUE, summary, what_it_funds,
         keywords json, funder_types json, search_queries json,
         min_award INTEGER NULL,      -- per-program override of the global floor
         active INTEGER,              -- ticked = searched this week
         source_url, created_at, updated_at)

funders(id TEXT PK, name, url, sector, funder_type, warm INTEGER,
        active INTEGER, programs json, notes, confidence, created_at, updated_at)

opportunities(id TEXT PK, run_id, found_on TEXT, month_key TEXT,  -- 'YYYY-MM'
              …every Opportunity field…, needs_human_check INTEGER)
CREATE INDEX idx_opp_month ON opportunities(month_key);

runs(id TEXT PK, started_at, finished_at, status, stop_reason, usd_spent,
     sources_attempted, sources_ok, sources_failed, candidates_parsed,
     rejected_by_filter json, scored, not_stated, notes json)
```

**Dedup is a primary-key lookup** — `SELECT 1 FROM opportunities WHERE id = ?` on a
`TEXT PRIMARY KEY`, which SQLite serves from the index in effectively constant time. It
runs in the deterministic tier, before any model call, so a repeat finding costs $0.00.

**Monthly purge**, exactly as specified: at the start of every run,
`DELETE FROM opportunities WHERE month_key < <this month>`. The archive therefore holds
the current month only, and a grant seen in July legitimately reappears in August. That
is the intended exception, and the run log records how many rows were purged so it is
never silent.

---

## §3 — Deliverables, in build order

Each is one commit, each ships with its own test.

| # | Deliverable | Test | Commit |
|---|---|---|---|
| 1 | Merge `origin/main` into `phyo-build` | existing suite still green | ✅ done |
| 2 | Remove the ~16-hours stat from all 5 files | `grep -r "16 hour"` returns nothing | `docs:` |
| 3 | SQLite store — schema, migrations, CRUD | `tests/test_db.py` — round-trip every table, dedup hit/miss, purge boundary | `feat(db):` |
| 4 | `$10,000` floor + config read from the DB | `tests/test_config.py` — DB beats Sheet beats defaults; placeholder machinery gone | `feat(config):` |
| 5 | FastAPI backend + Settings (encrypted key, write-only) | `tests/test_api_settings.py` — key never returned, masked hint only, live key-test endpoint | `feat(api):` |
| 6 | Program-card CRUD + Sonnet "build from a link" assistant | `tests/test_api_programs.py` + one real assistant call against risesandiego.org | `feat(api):` |
| 7 | Funder CRUD + sector tags + `DiscoveryProvider` seam | `tests/test_api_funders.py`; seam returns empty, pipeline unaffected | `feat(api):` |
| 8 | Monthly archive dedup wired into the crawl + purge on run start | `tests/test_archive.py` — second run of the same month yields 0 new | `feat(agent):` |
| 9 | The eleven attributes end-to-end (schema → gate → sink → UI) | `tests/test_accuracy_gate.py` extended to the new sourced fields | `feat(agent):` |
| 10 | Dashboard shell — sidebar, routing, Settings page, Archive page | `npm run build` clean; manual pass in `docs/TESTING.md` | `feat(dashboard):` |
| 11 | Dashboard main — program cards, funder list, run knobs, Re-run button | same | `feat(dashboard):` |
| 12 | Findings list, `needs_human_check` block sorted last | same | `feat(dashboard):` |
| 13 | **First real end-to-end LLM run** and its evidence artifact | the run itself; cost recorded against the $1 ceiling | `test:` |
| 14 | Every markdown file updated to the new architecture | `grep` sweep for stale claims | `docs:` |

### Deliverable 13 is the highest-value item in this list

The key in `.env` is live — verified with a real Haiku call while reading the repo.
`evidence/README.md` currently says, in bold, *"The LLM tiers have never run… treat every
score in this repo as unproven."* That is the single largest gap in the evidence package
and it can be closed today for about forty cents. It converts:

- Execution → *Experiments run* (10 pts): a real scored run against live funder pages.
- Use of AI → *Human-AI collaboration* (8 pts): the before/after when the model's first
  real scores get corrected.
- Use of AI → *Quality control* (5 pts): the accuracy gate firing on a real confabulation
  rather than on a fixture.

---

## §4 — Open questions for Mauri, ready for tomorrow

The build records these rather than guessing at them.

1. **The four sectors.** Every funder row carries a `sector` tag and the dashboard shows
   sector checkboxes. Currently seeded with `warm_partner / foundation / government /
   arts_agency / intermediary`. Her answer changes labels, not code.
2. **The other four programs.** ILIA Awards, RISE Now, On The RISE, and Nonprofit
   Trainings get seeded as inactive program cards. Ticking one is the entire activation.
3. **Match requirement** (§11 Q4) — still unanswered, still flagged not filtered.
4. **Forced-rank for the score weights** (§11 Q5) — still provisional in the prompt.
5. **The ten calibration fixtures** — still not hers, and the harness still says so.
6. **API-key ownership** (§11 Q6) — the Settings page makes this concrete: whoever pastes
   the key owns the bill.
7. **The real time-spent-searching number**, to replace the deleted stat.

---

## §5 — What this plan does not do

- No auth, no accounts, no multi-tenant. Still a §3 non-goal, still correct.
- No writing or submitting applications. The agent still stops at a ranked, sourced list.
- No deployment this weekend. Local-first, documented deploy path.
- No outside-the-warm-list discovery — that is the teammate's branch, and this plan builds
  only the seam it plugs into.
