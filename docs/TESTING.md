# Manual test guide — is the prototype actually working?

Run these in order on your machine. Everything through §4 needs **no API key and no
money**; §5 is the first real spend (~$0.10–0.30). By the end you'll know exactly what
works, with your own eyes — and you'll have the screenshots the rubric rewards.

Branch: **`phyo-build`** (`git checkout phyo-build`). Time: ~15 minutes.

Legend: ✅ = what a pass looks like · ⚠️ = expected caveat, not a bug.

---

## 0. Prerequisites
- Python 3.11+, Node 18+, git.
- Network (the free-tier run fetches real funder pages).
- Optional now: an Anthropic API key (your $100 hackathon credit) — only needed for §5.
- A Google account is **not** needed for any step here (export is a later phase).

## 1. One-time setup (~3 min)
```bash
git checkout phyo-build

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd dashboard && npm install && cd ..
```

---

## 2. Offline tests — no key, no network, no cost (~30 sec)

**2a. The accuracy gate** — the "never show a number that wasn't on the page" guarantee:
```bash
python3 tests/test_accuracy_gate.py
```
✅ `13/13 passed.`
Proves: a fabricated award, a paraphrased quote, and an *invented deadline year* are all
rejected; only a value whose verbatim sentence is literally on the fetched page survives.
This is the one failure CLAUDE.md §6 calls "fatal," now provably closed.

**2b. Calibration — filter sanity** (fixtures, deterministic, free):
```bash
python3 -m tests.calibration --dry-run
```
(run as a module from the repo root — plain `python3 tests/calibration.py` fails on imports)
✅ It ranks the 10 placeholder fixtures and prints
`✓ no YES was wrongly filtered; N NO(s) left for the model`.
⚠️ It will LOUDLY say the fixtures are **placeholders, not Mauri's**, and MIN_AWARD is a
placeholder. A pass means "the pipeline can rank," **not** "the model is calibrated."
Real calibration is blocked on Mauri's 5-yes/5-no (STAKEHOLDER.md Q8).

---

## 3. Free-tier pipeline run — no key, real funder pages (~1–2 min, needs network)
```bash
python3 -m agent.run --no-llm --sink web --max-tier 1 -v
```
Fetches the warm funders' own pages → parses → applies the free deterministic filters →
writes `dashboard/public/run.json`. No model calls, **$0.0000**.

✅ A `RUN SUMMARY` table prints (sources tried / ok / failed, pages parsed, amount found /
not stated, cost `$0.0000`, a `stop reason`), and the file exists:
```bash
python3 -c "import json; d=json.load(open('dashboard/public/run.json')); print('scored', len(d['scored']), '| not_stated', len(d['amount_not_stated']), '| cost', d['run']['usd_spent'])"
```
⚠️ With no LLM, most rows land in **amount_not_stated** and every score is `0` — the
deterministic parser only finds an amount on some pages, and nothing gets *scored*
without the model. That's correct and honest, not a failure. §5 fills in the scores.

---

## 4. The website — see the results render (~1 min)
```bash
cd dashboard && npm run dev
```
Open the printed URL (usually http://localhost:5173).

✅ The page loads from `/run.json` and shows: a "worth a look" count, a this-run cost
bar, "sources checked," and opportunity cards (funder, title, award range if any,
deadline + days left, programs, a **view source ↗** link, and a **needs a human check**
badge where the amount/deadline wasn't sourced).

Spot-checks (do these — they're the whole point):
- Click **view source ↗** on a card → it opens the funder's own page.
- Confirm **no card shows a dollar amount or a deadline you can't find on that linked
  page.** (This matters most after §5, when the model is involved.)

⚠️ If the page says "No results yet," you haven't run §3 yet (or ran with a different
`--web-out`).

---

## 5. The LLM tier — the real scoring (needs a key, ~$0.10–0.30)
This is the **first time Haiku triage + Sonnet scoring actually run.** They never had:
the old code used a nonexistent model ID (`claude-sonnet-5`) that would 404 on every
call. It's now `claude-haiku-4-5` (triage) + `claude-sonnet-4-6` (scoring).
```bash
export ANTHROPIC_API_KEY=sk-ant-...      # your hackathon key
python3 -m agent.run --max-tier 1 --budget 0.30 -v --sink web
```
✅ Expect:
- log lines: `triage <title> -> True/False (...)` (Haiku) and `scored NN <funder> <title> ($0.00xxx)` (Sonnet);
- a `RUN SUMMARY` with **cost > $0** and a `stop reason` of `target_met` / `sources_exhausted` / `budget`;
- `dashboard/public/run.json` now has **scored rows with scores + one-sentence
  rationales** — refresh the browser tab to see them ranked.

**Watch the A1 gate work.** In the `-v` output, look for:
```
⚠ award unverified (quote not on page) — nulling ...
⚠ deadline unverified (quote/year not on page) — dropping ...
```
Each line is the gate catching a number the model couldn't source, nulling it, and
flagging the row for a human. **Screenshot one** — it's your strongest QC evidence
("the agent refuses to fabricate"). If you see none, spot-check a few source links to
confirm every shown number is real (either outcome is a pass).

Confirm the models actually used (attribution evidence):
```bash
grep -nE 'TRIAGE_MODEL =|SCORING_MODEL =' agent/score.py
# TRIAGE_MODEL = "claude-haiku-4-5"   /   SCORING_MODEL = "claude-sonnet-4-6"
```

---

## 6. Safety controls
- **Budget ceiling** (forces an early stop so it can never overspend):
  ```bash
  python3 -m agent.run --max-tier 3 --budget 0.05 -v --sink web
  ```
  ✅ `stop reason: budget` and the run aborts partway. This is the demoable "$1 kill."
- **Kill switch** (`ENABLED=FALSE`) exits at step 0 — **only testable once a Google
  Sheet Config tab + service account are wired.** See §8: in the website-first design we
  still need to decide where config lives, so treat this as not-yet-verifiable.

---

## 7. Capture evidence while you test (free rubric points)
Drop these in `evidence/screenshots/` with a one-line caption each:
- `13/13 passed` (accuracy gate) → Quality control (5) + Transparency (2)
- calibration output **before** any weight tuning → the "before" for Human-AI collaboration (8)
- the dashboard with real **scored** results → Tangible outputs (10)
- a `⚠ … unverified` gate line + the run's cost line → Experiments (10), the "refuses to fabricate" beat

---

## 8. Honest status — what is NOT done or not testable here
Say this out loud in the demo; it's transparency, and it's true.
- ❌ **Weekly GitHub Actions cron + auto-committed `run.json`** — `weekly.yml` still targets
  `--sink sheets` and has not been repointed to `--sink web` + a git-commit step, and has
  never run on GitHub (needs the `ANTHROPIC_API_KEY` secret + a live run). *Next.*
- ❓ **Where config + the kill switch live in the website-first world** — today they're in
  a Google Sheet read via a service account. If Mauri now works on the website, we need to
  decide where she edits the award floor and flips `ENABLED`. Open decision.
- ❌ **Pruning UI** (keep/reject on the website) — Phase 2.
- ❌ **Gmail OAuth export to her Sheet** — Phase 3 (needs a Google OAuth client + Mauri as
  a listed test user).
- ❌ **Real calibration** — placeholder fixtures until Mauri gives her 5 clear-yes / 5
  clear-no.
- ⚠️ **`dashboard/api/runs.js` is now unused** — the dashboard reads `/run.json` directly.
  Safe to delete; left in place for now.

---

## Definition of "working prototype" — the checklist
- [ ] §2a accuracy gate: `13/13`
- [ ] §2b calibration `--dry-run`: no YES wrongly filtered
- [ ] §3 free-tier run writes a valid `run.json`
- [ ] §4 dashboard renders results from `run.json`; source links open the funder page
- [ ] §5 LLM tier runs with a key → scored rows with rationales, cost within budget
- [ ] §5 every displayed amount/deadline is verifiable on its source page (A1 gate)
- [ ] §6 budget ceiling forces an early stop when set low

All boxes checked = a working prototype: **agent → sourced, scored, accuracy-gated
results → website.** What's left (§8) is delivery polish and deployment, not core
function.
