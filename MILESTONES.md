# Milestones — Rise San Diego (team 8)

Local mirror of what we have submitted to the AI Trailblazers leaderboard, and **why
each one counted**. The board itself only stores a count; this file is the only place
the reasoning survives.

- **Event:** `sd-2026-08` — Social Impact HackAIthon, San Diego, Aug 1–2 2026
- **Team id:** `rec2cpmZOA0qQrQX9`
- **Board:** https://aitrailblazers.org/hackathon-sd/leaderboard

> **Why this file exists.** The leaderboard API has no `GET /events` route — you can
> `POST /event`, read `/config`, and read `/leaderboard`, and that is all. `/leaderboard`
> returns per-team counts and a map of **verified** categories only, so a pending
> milestone is invisible there and the notes you wrote are not retrievable at all.
> If it is not written down here, it is gone.

## Status as of Sun Aug 2, 2026

| | |
|---|---|
| Verified | 2 |
| Pending mentor verification | 2 |
| Categories verified | `stakeholder-conversation: 2` |
| Categories pending | `teammate-hygiene: 2` |

⚠️ **Pending milestones are invisible on the board.** `/leaderboard` only reports
*verified* categories, which is why M3 looked unlogged until we checked our own records.
Do not re-log something because the board does not show it — check here first.

---

## Submitted

### M1 — Stakeholder conversation (verified ✅)

| | |
|---|---|
| **Category** | `stakeholder-conversation` |
| **Event ID** | `TODO` |
| **Logged by** | `TODO` |
| **When** | `TODO` |
| **Source** | self_reported → **verified by a mentor** |

**Who we talked to:** `TODO — name, role, organisation`

**What happened / what we learned:** `TODO`

**Why it counted:** `TODO — the category is "talked to one real person the mission
serves or depends on"`

**Evidence:** `TODO — link, transcript, or notes`

---

### M2 — Stakeholder conversation (verified ✅)

| | |
|---|---|
| **Category** | `stakeholder-conversation` |
| **Event ID** | `TODO` |
| **Logged by** | `TODO` |
| **When** | `TODO` |
| **Source** | self_reported → **verified by a mentor** |

**Who we talked to:** `TODO — name, role, organisation`

**What happened / what we learned:** `TODO`

**Why it counted:** `TODO`

**Evidence:** `TODO`

---

### M3 — Teammate hygiene (pending ⏳)

| | |
|---|---|
| **Category** | `teammate-hygiene` |
| **Event ID** | `recOgPBvN9nUNo8uQ` |
| **Logged by** | Phyo Thant |
| **When** | Sat Aug 1, 2026 — evening |
| **Source** | self_reported → **still pending**, no mentor has verified it |

**The note as posted, verbatim:**

> Vetted our AI tooling instead of trusting it blind: read all 3 of the telemetry
> plugin's hook scripts and confirmed they make no network calls (local queue only)
> before enabling; verified the leaderboard key against /config (HTTP 200); read +
> human-vetted a 13-agent review workflow's output, accepting/rejecting its
> architecture findings ourselves; and our agent ships a spreadsheet-cell kill switch
> (ENABLED) the COO can flip to stop it.

**Why it counted:** the category is *"evidence the team is steering AI teammates well:
traces read, work verified, a kill switch in place."* This hits all three — hook scripts
read before enabling, a multi-agent review's findings accepted/rejected by humans rather
than applied wholesale, and a kill switch shipped in the product.

**Note for the demo:** the kill switch has since moved. It was a spreadsheet cell
(`ENABLED` in the Sheet's Config tab); it is now a tick box on the dashboard, plus a
**Stop the search** button that terminates a running search. The claim still holds and
got stronger — see `docs/PLAN.md` §0 for why config moved off the Sheet.

**Evidence:** `agent/config.py` (fail-closed config load), `evidence/README.md` E7 (the
kill switch verified with a socket guard, not by reading the code), `docs/DECISIONS.md`.

---

### M4 — Teammate hygiene, second instance (pending ⏳)

| | |
|---|---|
| **Category** | `teammate-hygiene` |
| **Event ID** | `recbhVUsYto1Pe5P9` |
| **Logged by** | Phyo Thant |
| **When** | Sun Aug 2, 2026 |
| **Source** | self_reported → **pending** |

**The note as posted, in short:** on the first real scored run the accuracy gate fired
three times and discarded two award amounts and a geography the model had reported. That
reads like the guard working. We fetched the funder pages to check **before** claiming
it, and found the opposite — Sonnet had read *"Up to $150,000"* correctly and **our**
parser was mangling it into `$\n150\n,\n000`, so the gate was throwing away a **true**
value. Fixed both halves; records with a sourced award amount went 0 → 1 on the same
crawl. Added a regression test asserting a fabricated `$500,000` quote is *still*
rejected against the same repaired page, so the fix cannot launder a hallucination.

**How it maps to the category:**

| Category phrase | What happened |
|---|---|
| "traces read" | Read the run's own warning lines (`⚠ award unverified — nulling 150000`), not just the summary |
| "work verified" | Fetched the live Prebys page and inspected the raw extracted text before accepting our own conclusion |
| "kill switch in place" | Dashboard toggle plus a **Stop the search** button that terminates a running search |

**How it is distinct from M3** (the obvious challenge): M3 was vetting **third-party
tooling before enabling it** — hook scripts, the API key, a review workflow's output.
M4 is verifying **our own product's AI output against ground truth in production**.
Different day, different artifact, different failure mode. The note says so explicitly
so a mentor does not have to work it out.

**The defence if pushed on "isn't this just a bug fix":** the bug is the least
interesting part. We were one paragraph from writing up *"our gate caught two
hallucinations"* as a win, and it was false. **"Our safety check fired" is not the same
as "our safety check was right"**, and the difference only appears if you go and look.

**Evidence:** `evidence/README.md` E11 + E12 · commit `5f1c4d6` ·
`evidence/runs/block5-first-real-llm-run.txt` vs `block5-after-split-amount-fix.txt`

**Caveat stated in the note itself:** those commits were local and unpushed at the time
of logging.

---

## Not yet submitted — candidates

### C1 — Asset shipped (hold until pushed)

The app runs (`./start.sh` → `localhost:8000`), 66 tests pass, 10 commits are on
`phyo-build`. But the category says *"live and **reachable**"* and right now the commits
are **local only and unpushed**, so nobody but us can reach any of it. Logging it after
the push — with the repo URL as evidence — turns a contestable claim into a solid one.

---

## Rules we are holding ourselves to

- Never log the same category twice for the same underlying work. M3 and C1 are
  different work on different days, and the notes say how.
- Never self-promote `self_reported` to verified. Only mentors do that.
- Log the weakness in the note. A mentor who finds the caveat themselves trusts the rest
  of the entry less.
