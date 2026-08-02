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
| 1 | **Smallest award worth 10 hours of team time?** | `MIN_AWARD`, the primary filter | ❌ **UNANSWERED — top priority.** Running on a `$25,000` placeholder that is labeled as such in the Config tab, in the run output, and here. Not an answer. |
| 2 | Candid / Foundation Directory / Instrumentl access? If not, which ~20 funder pages? | crawl scope | ⚠️ Partial. Built from the 8 warm funders in §7. See "New questions" below. |
| 3 | Government contracts and RFPs too, or grants only? | doubles source scope | ❌ Unanswered. Tier 3 registered but disabled. |
| 4 | Can RISE meet a 1:1 match requirement? | hard filter | ❌ Unanswered. Filter not written. |
| 5 | Forced-rank: award size / win likelihood / program fit / funder warmth / low reporting burden | score weights §7 | ❌ Unanswered. §7's placeholder 35/25/20/15/5 is in the scoring prompt, labeled PROVISIONAL. |
| 6 | Who owns the Anthropic API key and this repo after Sunday? Name + payment method. | handoff §12 | ❌ Unanswered. **An unmaintained scheduled job is a liability, not an asset.** |
| 7 | Annual operating budget and EIN | Org Profile tab | ❌ Unanswered. Funders filter on these. |

**Also blocking, and missing from CLAUDE.md §11:**

| # | Question | Blocks | Status |
|---|---|---|---|
| 8 | **The 5 clear-yes and 5 clear-no opportunities for the calibration test.** | `tests/calibration.py` — §10 calls it "the only test that matters" | ❌ Unanswered. Block 2 cannot be verified without it. |
| 9 | **How much time does searching for funding actually take you in a week?** | the before/after claim in the demo and in every doc | ❌ Unanswered. An earlier draft carried "~16 hours/week"; RISE's team says that figure is not correct, so it has been **removed from every file in this repo** rather than left standing. We would rather have a gap than a wrong stat about a real person. |
| 10 | **What are the four sectors you want funding found in?** | `sector` tags on the funder registry and the sector checkboxes in the dashboard | ❌ Unanswered. Seeded with `warm_partner / foundation / government / arts_agency / intermediary` as a placeholder taxonomy; her answer is a label change, not a code change. |

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
