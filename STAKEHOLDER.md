# Stakeholder record — RISE San Diego

Tracks what we asked Mauri, what she answered, and what anyone committed to.
The rubric scores **Stakeholder evidence (10)** and **Commitments or next steps (10)**
— 20 of 100 points, and the first tie-breaker. This file is where that evidence lives.

**Stakeholder:** Mauri Hamilton, COO, RISE San Diego — responsible for finding funding.
**Secondary:** Veronica Baker, Grant Writer — receives the handoff.

---

## What she told us (source: CLAUDE.md §1, from the intake conversation)

| Fact | Detail |
|---|---|
| Time spent searching | A substantial, recurring block of her week. **The specific number is an open question — see Q9.** |
| Reporting cadence | Thursday meeting |
| Effort ceiling per application | 10 collective hours, hard |
| The actual pain | *"doesn't guarantee the grants found are worth the application — mainly due to the low award amount."* |

The bottleneck is **not** discovery volume. An agent that finds more grants makes her
problem worse. Everything in this repo follows from that one sentence.

---

## Open questions — status

| # | Question | Blocks | Status |
|---|---|---|---|
| 1 | **Smallest award worth 10 hours of team time?** | `MIN_AWARD`, the primary filter | ✅ **ANSWERED: $10,000.** The placeholder and all its machinery are gone. Now editable on the dashboard, so it can be tuned after a fortnight of real results without a code change. |
| 2 | Candid / Foundation Directory / Instrumentl access? If not, which ~20 funder pages? | crawl scope | ⚠️ Partial — and it has stopped being a *code* question. The funder list is CRUD-editable in the dashboard, so adding twenty pages is data entry, not a deploy. Still worth asking which twenty. |
| 3 | Government contracts and RFPs too, or grants only? | source scope | ✅ **ANSWERED: yes, both.** Ticking the "Government RFPs & contracts" sector raises the crawl tier. Live — the first scored run attempted County of San Diego (it timed out; their site is slow, not missing). |
| 4 | Can RISE meet a 1:1 match requirement? | hard filter | ❌ Unanswered. Filter still not written; matches are flagged and passed through rather than guessed at. |
| 5 | Forced-rank: award size / win likelihood / program fit / funder warmth / low reporting burden | score weights §7 | ❌ Unanswered. §7's 35/25/20/15/5 is in the scoring prompt, labeled PROVISIONAL. |
| 6 | Who owns the Anthropic API key and this repo after Sunday? Name + payment method. | handoff §12 | ❌ Unanswered — but now **concrete**: whoever pastes a key into the Settings page is paying. Measured cost is **$0.18/run, under $1/month**, so this is a decision about ownership, not budget. |
| 7 | Annual operating budget and EIN | funders filter on these | ❌ Unanswered. |

**Also blocking, and missing from CLAUDE.md §11:**

| # | Question | Blocks | Status |
|---|---|---|---|
| 8 | **The 5 clear-yes and 5 clear-no opportunities for the calibration test.** | `tests/calibration.py` — §10 calls it "the only test that matters" | ❌ Unanswered. Block 2 cannot be verified without it. |
| 9 | **How much time does searching for funding actually take you in a week?** | the before/after claim in the demo and in every doc | ❌ Unanswered. An earlier draft carried "~16 hours/week"; RISE's team says that figure is not correct, so it has been **removed from every file in this repo** rather than left standing. We would rather have a gap than a wrong stat about a real person. |
| 10 | **What are the four sectors you want funding found in?** | `sector` tags on the funder registry and the sector checkboxes in the dashboard | ❌ Unanswered. Seeded with `warm_partner / foundation / government / arts_agency / intermediary` as a placeholder taxonomy; her answer is a label change, not a code change. |

---

| # | Question | Blocks | Status |
|---|---|---|---|
| 11 | **risesandiego.org lists TEN programs, not seven.** We were told seven; the site also shows Community Impact Showcase, RISE Urban Breakfast Club, and RISE Consult. Do those need funding too, or are they not fundraising targets? | which cards ship seeded | ❌ Open. All seven named ones are seeded; the other three are not. Adding one is a button press. |
| 12 | **The four non-priority program cards are empty.** ILIA, RISE Now, On the RISE, Nonprofit Partnerships Training have a name and a real URL and nothing else — we would not invent descriptions of RISE's own programmes. | how well those programs get matched | ❌ Open, and it takes ten minutes: Edit → paste the program's link → "Read this page for me" → correct it → Save. Demonstrated working on ILIA (evidence E14). |

---

## New questions the first crawl produced

These came out of running the agent against real pages, not from speculation.

1. **The Morales Fund and The Villegas Fund have no findable public grants page.**
   Both are listed as warm in §7. Neither appears to publish an open call. Are they
   relationship-only? If so they belong on the **Funders** tab as warmth records, not
   in the crawl registry — the agent cannot watch a page that does not exist.

2. **No funder in tier 1 states a deadline in machine-readable text.** Across 28 pages
   fetched, zero deadlines were extracted. Deadlines appear to live in PDFs, in
   application portals, or nowhere. This directly threatens the "deadline runway"
   filter and the deadline column. **Does Mauri want deadline-less opportunities
   surfaced at all?**

3. **Most funder pages never state an award amount.** 21 of 23 records had no per-award
   figure on the page. Since `MIN_AWARD` is the primary filter and the entire product
   thesis, this is the central design problem, not a detail. Current behavior: they go
   to a separate labeled block rather than being dropped or faked.

4. **Confirm the reject list.** §7 rejects the County of San Diego Equity Impact Grant
   as "done, no more funding." The crawl found other County programs (CDBG). Confirm
   the reject is that one program, not the County entirely.

5. **Two warm funders mention a matching requirement.** The Prebys *2025 Arts
   Ecosystem: Venues & Spaces* page and the California Arts Council *Grant Applicant
   FAQs* both reference matching funds. Because §11 Q4 is unanswered we cannot filter
   on it — the agent flags these and passes them through rather than guessing. **This
   is question 4 becoming concrete: it is already affecting warm funders, not a
   hypothetical.**

---

## Commitments secured

> Nothing recorded yet. **This is 10 rubric points sitting empty and the first
> tie-breaker.** Fill it in as things land.

| Date | Who | Commitment | Evidence |
|---|---|---|---|
| | | | |

Things that count: a follow-up meeting, agreement to pilot for a month, a named owner
for the API key, Veronica agreeing to use the output, an intro to a funder, budget
approved for the ~$6/month API spend.

---

## Decisions we made against the stakeholder's stated ask

Worth stating out loud in the demo — the rubric scores **Human-AI collaboration (8)**
on whether the team *directed and corrected* the work using domain knowledge.

**She asked for:** "the agent won't stop until it finds the target number."
**We built:** a cap, not a quota.

A quota forces the agent to pad the list with low-value opportunities — which is
precisely the problem she is hiring us to solve. Six good results is a good week.
This was a deliberate refusal, made because we understood the underlying need better
than the literal request. (CLAUDE.md §8.)

---

## Decisions we made against our own earlier work

These are corrections, not features. Worth saying out loud for the same reason.

**We deleted a statistic about her.** An early draft of the spec recorded "~16 hours a
week searching for funding" and it propagated into five files — including
`agent/score.py`, where it was being asserted to the model as fact on every scoring
call. RISE says the number is not right. It is now gone from every file, replaced by
nothing rather than by another estimate, and logged above as Q9. The argument for the
product never depended on the number, only on her own sentence about low award amounts.

**We nearly claimed a win we had not earned.** The accuracy gate fired three times on
the first real scored run, discarding two award amounts and a geography the model had
reported. That reads like the guard working exactly as designed, and we were one
paragraph from writing it up that way. Checking the funder pages first showed the
opposite: the model had read *"Up to $150,000"* correctly, and our own parser had
mangled it into `$\n150\n,\n000`, so the gate was throwing away a **true** value.

Both halves got fixed and records with a sourced award amount went 0 → 1 on the same
crawl. The full sequence is in `evidence/README.md` E12. The point is not the bug — it
is that "our safety check fired" is not the same as "our safety check was right", and
the difference only shows up if you go and look.
