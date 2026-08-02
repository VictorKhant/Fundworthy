# Manual test guide — is the prototype actually working?

Run these in order on your machine. Everything through §3 needs **no API key and no
money**; §4 is the first real spend (~$0.20). By the end you'll know exactly what works,
with your own eyes — and you'll have the screenshots the rubric rewards.

Branch: **`phyo-build`**. Time: ~15 minutes.

Legend: ✅ = what a pass looks like · ⚠️ = expected caveat, not a bug.

---

## 0. Prerequisites

- Python 3.11+, Node 18+, git.
- Network (the free-tier run fetches real funder pages).
- Optional until §4: an Anthropic API key.
- A Google account is **not** needed for any step here.

---

## 1. Start it (~2 min the first time)

```bash
./start.sh
```

✅ It installs what it needs, builds the dashboard, and prints
`RISE Fund Finder → http://localhost:8000`. Open that.

✅ You should see the main dashboard with:
- **This week's search** — the knobs, with the award floor showing **$10,000**
- **Programs to find funding for** — 7 cards, 3 ticked (Arts, Resilience, RULFP)
- **Funders we watch** — 8 partners plus 6 others
- a banner saying no API key is saved yet

⚠️ On a fresh clone the findings list is empty. That is correct — nothing has run.

---

## 2. Offline tests — no key, no network, no cost (~5 sec)

```bash
.venv/bin/python -m pytest tests/ -q
```

✅ `66 passed`. That covers:

| File | What it proves |
|---|---|
| `test_accuracy_gate.py` | A fabricated award, a paraphrased quote, and an invented deadline year are all rejected. Only a value whose verbatim sentence is literally on the fetched page survives. Includes the regression for split-across-elements amounts (evidence E12). |
| `test_db.py` | Dedup hits and misses, the purge boundary in both directions, funder deactivation keeping the record, and the reading order Mauri asked for. |
| `test_api.py` | Every endpoint, and — the ones that matter — that **no endpoint returns the API key**, that it is not in the `.db` in plaintext, and that a corrupt key file degrades instead of 500-ing. |

**The one worth reading the assertion for:**

```python
def test_api_key_is_never_returned_by_any_endpoint(client):
    for path in ("/api/settings", "/api/state", "/api/programs", ...):
        assert FAKE_KEY not in client.get(path).text
```

**Calibration — filter sanity** (fixtures, deterministic, free):

```bash
.venv/bin/python -m tests.calibration --dry-run
```

✅ `5/10 killed by free filters; no YES wrongly filtered.`
⚠️ It says the fixtures are **not Mauri's**, on every run. That is the point — a pass
proves the pipeline ranks, not that it is calibrated. It also has not been re-checked
since the floor moved from $25,000 to $10,000.

---

## 3. A free run against real funder pages (~2 min, $0.00)

```bash
.venv/bin/python -m agent.run --no-llm
```

✅ 6 of 7 sources fetch (County of San Diego frequently times out — their site is slow).
✅ ~28 pages parsed, ~17 survive, everything else rejected **before any model call**.
✅ `cost $0.0000`.

**Now run it a second time.** This is the dedup test:

```bash
.venv/bin/python -m agent.run --no-llm
```

✅ `0 candidates survived` and `17 already_seen_this_month` in the reject table.
✅ Still `$0.0000`. The repeat cost nothing because dedup runs in the free tier.
⚠️ The findings on the dashboard do **not** disappear — `run.json` and the database keep
the month's results. (That was a bug, found by running this exact test; see E13.)

To see repeats again: `.venv/bin/python -m agent.run --no-llm --no-archive`

---

## 4. The paid tiers — the first real spend (~3 min, ~$0.20)

Put a key in on the **Settings** page, press **Check it works** (✅ *"That key works."*),
then press **Re-run search pipeline** on the main page.

✅ The log streams live under the button, and **Stop the search** genuinely stops it.
✅ Cost lands around **$0.18** against the $1.00 ceiling.
✅ Haiku triage kills ~11 more candidates that got past the free filters.

**Watch for lines like this — they are the guarantee working:**

```
⚠ award unverified (quote not on page) — nulling None/250000
⚠ geography_stated unverified (quote not on page) — dropping 'San Diego'
```

That is a value the model reported being **thrown away** because the sentence backing it
was not on the page. Do not treat those as failures. And do not treat them as wins
either without checking the page — that is exactly the mistake E12 records.

On the dashboard:
✅ Results with a sourced amount sort above results without one.
✅ **Needs your eyes** is its own block, at the bottom.
✅ Values with a dashed outline and an **AI** tag are the model's judgement; everything
else was read off the funder's page.

---

## 5. The card assistant (~30 sec, ~$0.015)

Programs → any empty card (ILIA, RISE Now, On the RISE, Nonprofit Partnerships
Training) → **Edit** → the link is already filled in → **Read this page for me**.

✅ The card fills in: summary, what it funds, keywords, search queries, funder types.
✅ It tells you what it could **not** find and how useful it thought the page was.
✅ Nothing is saved until you press Save.

That flow is the answer to CLAUDE.md §2 — she never writes a prompt, she corrects a
draft about her own programme.

---

## 6. The kill switch

Untick **"The agent is switched on"** → Save → press **Re-run search pipeline**.

✅ It refuses: *"The agent is switched off. Turn it back on in Settings first."*
✅ No network call is made.

For the pipeline itself, the same switch is read at step 0 — verified previously with a
socket guard that raises on any outbound connection (evidence E7).

---

## What this guide does NOT prove

- That Mauri can use it. Nobody at RISE has opened it.
- That the scores match her judgment. The calibration fixtures are ours.
- That the scheduled GitHub Actions run works. It has never executed, and it reads
  config from a different place than the dashboard — see the note at the top of
  `.github/workflows/weekly.yml`.
