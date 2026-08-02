# Handoff — RISE San Diego funding agent

For RISE San Diego. Written in plain language on purpose: nothing here needs a
developer to read. If a sentence in this file requires technical knowledge to act on,
that is a bug in the file — tell us.

---

## What it does

It visits the websites of the funders RISE already has relationships with and reads
their grant pages. It throws out anything too small, anything closing too soon, and
anything RISE cannot apply for — before spending a cent. What survives shows up on your
dashboard, sorted best-first, with a one-line reason and a link to the funder's own
page. Press **Re-run search pipeline** whenever you want it, or leave the Wednesday-night
schedule on so it is waiting for you Thursday morning.

**What it deliberately does not do:** it does not try to find *more* grants. Finding
them was never the hard part — the problem is that most of what turns up is too small
to justify a 10-hour application. So this agent is built to return **few** results.
Six good ones is a good week. If it returns three, that is not a malfunction.

It also never writes an application, never emails anyone on RISE's behalf, and never
states a dollar amount or deadline it did not read on the funder's own page. When it
cannot find one, it says "not stated" instead of guessing.

---

## How to open it

Double-click **`start.sh`** — or, in a terminal, run `./start.sh` from this folder.
It prints a web address (`http://localhost:8000`). Open it in a browser.

The first time takes about a minute while it installs itself. After that it is instant.

Everything lives on this computer. Nothing is on the internet, and there is no password,
because there is nothing to log into.

---

## How to change what it looks for

**All of it is on the main page.** Type in a box, press Save.

| Setting | What it does |
|---|---|
| **Smallest award worth applying for** | **The most important one.** Currently **$10,000**. Anything smaller is never shown to you. |
| **Download as a spreadsheet** | Button in the page header. The same columns as the Sheet. |
| **Ignore anything due sooner than** | 14 days. Less runway than that and a good application isn't possible. |
| **Most results to bring back** | 12. Sized for a one-hour review. |
| **Most to spend on one search** | $1.00. It stops rather than going over. |
| **Where to look** | Which kinds of funder to search: partners, foundations, government RFPs, arts agencies. |
| **The agent is switched on** | See "How to stop it" below. |

### Programs

Each RISE program is a card. **Tick the ones you want searched this week** — that is the
whole activation. Three are ticked to start: Urban Leadership Fellows, Resilience &
Renewal, and Arts.

Four more (ILIA, RISE Now, On the RISE, Nonprofit Partnerships Training) are there but
**empty**, on purpose — we only put in what you told us, and we were not going to make
up a description of your own programme. To fill one in: press **Edit**, paste that
program's page from your website, and press **"Read this page for me."** The assistant
reads the page and fills the card in for you. **Read it over and fix anything wrong**
— it will tell you what it could not find. Nothing is saved until you press Save.

A card can also have its own award floor, if one program will take smaller grants than
the others.

### Where it looks

Two kinds of source, and results say which they came from:

- **Funder pages** — the organisations RISE already has relationships with. These are
  searched **first**, every run.
- **Public grants databases** — the California Grants Portal (every state agency is
  required by law to post its grants there) and Grants.gov (every federal grant).
  These are complete public lists rather than one funder's page, so they are broader
  but come with no relationship attached. They get whatever room is left after the
  partners.

A programme with an empty card contributes nothing to the database searches, and the
run says so by name rather than quietly returning less.

### Funders, and the remove list

60 funders are watched. Most were researched for you — every one had its grants page
opened and read before it went on the list, and each carries a sentence from that page
showing it funds nonprofits.

The important control is the **tick box on the left**:

- **Already getting money from them?** Untick. That is the whole point of the remove
  list: you told us you do not want opportunities from funders you already have, because
  you get those cheques without reapplying. An unticked funder is never visited, never
  read, and never scored — so it costs nothing every week rather than a little every
  week. It asks why, and remembers.
- **A funder stops funding you?** Untick them too. Same effect, and the record of the
  relationship stays.
- **Remove** is for a row that was simply wrong. It deletes the record.

New funders can be added with a name and their grants page.

**Nothing is on the remove list to begin with.** The eight funders we had marked as
"partners" came from your 2025 Impact Report — that is who has funded you *before*,
which is not the same as who funds you *reliably*. You know which is which; we did not
want to guess and drop something real.

---

## How to stop it

**Untick "The agent is switched on"**, at the bottom of *This week's search*.

Nothing runs — no searching, no spending — until you tick it back on. Nothing is
deleted; your existing results stay.

You do not need to call anyone or open a terminal. And if a search is running right
now, the **Stop the search** button ends it immediately.

For the scheduled Wednesday-night run, the same switch applies. If the settings cannot
be read at all, the agent **refuses to run** rather than assuming it should — guessing
"on" could ignore a decision you made to turn it off.

---

## What it costs, and who owns it

| | |
|---|---|
| **Anthropic API (the AI)** | **~$0.80/month** at current volume — a measured full run costs **$0.18**, not an estimate. Hard ceiling of $1.00 per run, enforced in code: it stops and says why rather than overspending. |
| **The app itself** | Free. It runs on your computer. |
| **GitHub Actions (optional scheduler)** | Free |
| **Total** | **under $1/month**, against a $20/month ceiling |

**Where the key goes:** the **Settings** page, one box, once. It is encrypted on this
computer, and nothing — not the page, not the API, not a screenshot — will ever show it
back to you beyond its last four characters.

> ⚠️ **Nobody owns the API key yet.** This is unresolved and it is the thing most
> likely to quietly kill the project. Whoever's key is pasted into Settings is paying
> the bill, so that needs to be a decision someone made, not one that happened. Until
> there is a key the agent still fetches and filters, but nothing gets read or scored.

Owner: `________________________`  ·  Payment method: `________________________`

---

## Where your data lives

One file: **`data/rise.db`**, in this folder. It holds your settings, your programs,
your funder list, this month's findings, and the encrypted key.

**Back it up by copying that file.** Restore it by copying it back.

> ⚠️ Do not email that file or put it in a shared folder — the encrypted key is in it,
> and the key that unlocks it (`data/.fernet-key`) is right next to it.

**The archive keeps the current month.** When a search runs in a new month, the previous
month's rows are cleared. That is deliberate: it is what stops you being shown the same
grant every week, and it means anything still open gets a fresh look next month rather
than being hidden forever.

---

## When it breaks

Under *This week's search*, the app tells you in plain English what the last run cost
and how it ended, with the agent's own log underneath. **Look there first.**

| What you see | What it means | What to do |
|---|---|---|
| "Could not reach the app" | The app is not running | Run `./start.sh` again |
| "The agent is switched off" | You unticked the switch | Tick it back on |
| "Hit the spending limit and stopped" | It protected the budget | Normal. Results are valid, just fewer. |
| "Checked every funder on your list" | Normal, healthy run | Nothing |
| **Nothing new found** | Everything it found, you have already seen this month | Normal. Check **Archived findings**. |
| Results appear but nothing is scored | No API key saved, or it expired | Settings → paste a key → **Check it works** |
| "That key was rejected" | The key is wrong or revoked | Get a new one from console.anthropic.com |
| A funder shows "couldn't reach" repeatedly | They changed their website | Edit that funder and fix the address |
| **Needs your eyes** on most results | The funders' pages don't state amounts | Expected — see below |
| "Something went wrong" | Read the log underneath | If it repeats twice, escalate |

### Why so many results say "Needs your eyes"

Most funders do not put an award amount or a deadline in plain text on their website —
we checked, across 28 pages, and it is a fact about them rather than a fault in the
tool. When the agent cannot find a number **on the funder's own page**, it leaves the
field blank and flags the row instead of guessing.

That is the single most important rule in this tool. A made-up deadline that costs you
a submission is far worse than a blank you can fill in with one click on the link.

**Nothing here is urgent.** A missed week costs one week of results. Do not let anyone
tell you this needs an emergency fix.

**Who to call:** `________________________`

### Running it by hand

Press **Re-run search pipeline** on the main page. It streams what it is doing as it
goes, and **Stop the search** ends it immediately.

There is also a Wednesday-night schedule on GitHub → **Actions** → **Weekly funding
run** → **Run workflow**, if RISE wants it. It has never been switched on.

---

## Honest limitations

Things we know are wrong or unfinished. Read these before trusting a result.

1. **Mauri has not used this yet.** It was built from one conversation and a follow-up.
   Everything about how it fits her week is our best guess until she opens it.

2. **The scores have never been calibrated against Mauri's judgment.** §10 of the spec
   calls for five opportunities she considers a clear yes and five a clear no; the test
   exists and runs, but on **placeholder examples we wrote ourselves**. It proves the
   pipeline can rank. It does not prove it ranks the way she would.
   **Treat every score as a starting point for her judgment, not a substitute.**

3. **Almost no funder publishes a deadline we can read.** Across 28 pages we extracted
   zero. We widened the patterns and re-ran; still zero. Deadlines live in PDFs, in
   application portals, or nowhere public. **Always confirm the deadline on the
   funder's page before committing to an application.**

   Related and worth knowing: on the first scored run, one Prebys programme whose
   deadline had already passed still reached the list. The AI *said so* in its
   one-line reason and scored it 15 out of 100 — but because it could not prove the
   date against the page, the automatic "too late" filter never fired. **Open item.**

4. **Most funder pages never state an award amount.** Those rows go to the bottom, under
   *Needs your eyes*, unranked — there is no number to rank them by.

5. **`Has a 990 on file` is never filled in.** The column exists and is always blank.
   Nothing checks it yet; blank means unknown, not "no".

6. **The Morales Fund and The Villegas Fund are not being watched.** Neither appears to
   have a public grants page. If they are relationship-only, untick them and keep them
   as a record of the relationship. Someone should confirm.

7. **Two funders mention matching requirements** (Prebys Arts Ecosystem, CA Arts
   Council). We do not know what match RISE can meet, so the agent flags them and
   passes them through rather than filtering. Answering that would tighten the list.

8. **"Also look beyond the funders on my list" does nothing yet.** The checkbox is
   there and the plumbing behind it is built, but the piece that actually goes looking
   is still being written. A search with it ticked says so rather than pretending.
   (This is separate from the two public grants databases, which *are* live.)

9. **California only categorises grants for three of your programmes.** The state
   portal sorts its grants into its own categories, and we have mapped those onto
   Urban Leadership Fellows, Resilience & Renewal, and Arts. A programme outside those
   three gets no California results — Grants.gov still covers it, and the run says so
   by name each time rather than quietly returning less.

10. **Some values on a result are the AI's opinion, not facts from the page.** Those
   carry a dashed outline and a small **AI** tag — funder type, service areas, the
   percentage fit, the hours estimate. Everything without that tag was read off the
   funder's own page or left blank.

---

## The 30-day question

**An unmaintained tool is a liability, not an asset.**

Funders redesign their websites. When one does, this will report "couldn't reach" into
an empty room — and the failure mode is silence, which is the worst kind. It needs an
owner, not a maintainer: someone who opens it once a month and notices.

Making it local rather than a hosted service was partly about this. There is no server
to expire, no bill to lapse, no deploy to break. It sits in a folder and works. But the
flip side is real and should be said out loud: **it only exists on the computer it is
installed on, and only Mauri can see it.** If RISE wants the team to share one view,
that is a deployment, and a deployment needs authentication and an owner — see "For
whoever picks up the code".

AI Trailblazers runs a **paid apprenticeship program** that places people with
nonprofits for exactly this kind of ongoing maintenance. That is the realistic 30-day
answer, and it is worth raising with Mauri directly rather than hoping the team
absorbs it.

### First 30 days, in priority order

| # | Action | Owner | Why it matters |
|---|---|---|---|
| 1 | Get it open on Mauri's own computer | RISE + us | Nobody at RISE has run this yet. Everything else is guesswork until they have. |
| 2 | Name an API key owner + payment method | RISE | Under $1/month, but it needs a name on it |
| 3 | Mauri supplies 5 clear-yes / 5 clear-no grants | Mauri | Makes the scores trustworthy instead of plausible |
| 4 | Confirm the $10,000 floor after a fortnight of real results | Mauri | It is her number, but it should survive contact with the output |
| 5 | Fill in the four empty program cards | Mauri | Paste a link, press the button, correct it. Ten minutes. |
| 6 | Tell us the four funding sectors | Mauri | The categories are our guess; hers would be better |
| 7 | Watch four consecutive Thursdays | Mauri | Four weeks tells you whether it saves real hours |
| 8 | Decide: keep, widen, or switch off | Mauri | An honest kill decision beats quiet decay |

### What "working" looks like in four weeks

Mauri opens it Thursday morning, spends under an hour, and finds at least one
opportunity worth an application she would not otherwise have seen. If that is not
happening by week four, the answer is to change the award floor or turn it off — not to
add features.

---

## For whoever picks up the code

Read `docs/PLAN.md` first — it explains the current shape and the five places we
deliberately reversed `CLAUDE.md` rather than drifting from it. Then `CLAUDE.md` for the
original reasoning, `evidence/README.md` for what we tested and what broke (including
the bugs we shipped and caught), and `STAKEHOLDER.md` for the open questions.

```bash
./start.sh                                        # the whole app
.venv/bin/python -m pytest tests/ -q              # 126 tests, offline, no key
.venv/bin/python -m agent.run --no-llm --dry-run  # free, no key, writes nothing
.venv/bin/python -m tests.calibration --dry-run   # the test that matters most
```

### If you deploy it

Right now the app binds to `127.0.0.1` and has **no authentication**, which is exactly
what makes "no accounts, no login" (`CLAUDE.md` §3) an honest position rather than a
hole: it is not reachable, so there is nothing to authenticate. Putting it on a public
host inverts that. Before you do:

1. **Add authentication.** Every endpoint. There is a stored API key behind them.
2. `data/rise.db` and `data/.fernet-key` must be on a persistent, private volume. They
   sit next to each other, so anyone who can read the directory has both — move the
   key to the host's secret store (`RISE_KEYFILE` points wherever you like).
3. Tighten the CORS origins in `app/main.py`. They allow the local Vite dev server.
4. Decide who can press **Re-run**. It spends money.

The pipeline itself is unchanged and needs none of this — `python -m agent.run` works
headlessly, which is what the GitHub Actions workflow already does.

**The one rule that is not negotiable:** never let the agent state a deadline or a
dollar amount that is not on a page it actually fetched. Funders read this output. A
wrong deadline costs RISE credibility that is far more expensive than a missed grant.
`agent/verify.py` is what enforces it — and E12 in the evidence package is what happens
when you check whether it is working rather than assuming.
