# Fundworthy

**[Live site →](https://fundworthy.duckdns.org/)**

### [▶ Watch the demo](https://youtu.be/czNsetBg7q4)

[![Fundworthy demo](https://img.youtube.com/vi/czNsetBg7q4/maxresdefault.jpg)](https://youtu.be/czNsetBg7q4)

A weekly **funding-opportunity agent for nonprofits**. It watches the funders an
organization cares about and leaves a short, sourced, ranked list of what is worth
applying for — on a dashboard the organization controls.

**The problem it solves is not "find more grants."** A nonprofit can already find them;
the problem is that most of what they find is too small to justify the hours an
application takes. So the agent is built to return *few* results, every one above an
award floor, and to say "amount not stated" rather than guess.

## Run it

```bash
./start.sh              # deps + dashboard build + app on http://localhost:8000
```

That is the whole thing. First run installs dependencies; after that it is instant.

The pipeline on its own, without the UI:

```bash
python -m agent.run --no-llm            # free tiers only, $0.00, no key
python -m agent.run                     # + LLM scoring; needs a key; ~$1/run ceiling
python -m agent.run --dry-run           # crawl and report, write nothing
python -m pytest tests/ -q              # the test suite (offline, no key needed)
```

## Setup

Run `./start.sh`, open the page, go to **Settings**, paste an Anthropic API key, and
press **Check it works**. Everything else — the funder list, the programs, this month's
findings — is already seeded.

The key is **encrypted on disk and no endpoint returns it**; the page can only show the
last four characters. Whoever's key it is pays the bill, which at this volume is a couple
of dollars a month. Nothing is exposed to the internet — the app binds to localhost.

Putting it on a server instead? Then it needs a login, because the URL would otherwise be
a way for anyone to spend that key. Sign-in is built — Google, through Firebase, limited
to an allow-list of addresses — and it is step 8 of
[docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md). Configure it half-way and the app refuses
to start rather than come up open.

## Stopping it

Untick **"The agent is switched on"** in Settings. Nothing runs — no searching, no
spending — until it is turned back on. No terminal, no repo, no phone call.

## Where things are

| Path | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | The spec — what the product is and how it works today. Read it first. |
| [FUTURE.md](FUTURE.md) | The roadmap — multi-tenant, accounts, hosting at scale. |
| [docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md) | Putting it on an Oracle free-tier VM, step by step. |
| `start.sh` | One command to run everything. |
| `app/` | FastAPI backend — API, SQLite store, encrypted key, the Re-run button. |
| `agent/` | The pipeline — fetch, parse, free filters, tiered scoring, the accuracy gate. |
| `sinks/` | Where results go — SQLite (primary), a static JSON export, CSV, Sheets. |
| `dashboard/src/` | The React UI — sidebar, dashboard, archive, settings. |
| `tests/` | pytest — `calibration.py` is the ranking test. |
