# Fundworthy — UI roadmap

Implementation plan for the redesign in `Fundworthy.dc.html`. Written for an engineer
(or Claude Code) working in `VictorKhant/Fundworthy@main`.

**The prototype is the spec for layout, copy and interaction.** Open
`Fundworthy.dc.html` next to this file. Where the two disagree, the prototype wins on
visuals; this file wins on which files to touch and what must not break.

---

## Ground rules

1. **Nothing in `agent/` changes** except where a step says so explicitly (only R6 and
   R7 touch it). The pipeline's accuracy rules are not a UI concern.
2. **Do not weaken the sourced-vs-inferred distinction.** `styles.css` opens with four
   correctness requirements — `.chip.inferred`, `.opp-score`, `.opp.flagged`, `.costbar`.
   Every one of them survives in the prototype. If a restyle makes an AI judgement look
   like a quote from a funder's page, the change is wrong.
3. **Server-side permission checks stay.** Hiding a button is not a permission. Every
   `org.you_are_admin` guard in `Organization.jsx` has a server counterpart; keep both.
4. **`onboarding_done` stays the source of truth for "is this person new."** The comment
   block in `App.jsx` explains why it is a stored fact and not a deduction. R1 must not
   reintroduce the deduction.
5. Ship in the order below. R0 → R3 are independent; R4 onwards assume R0 landed.

---

## R0 — Theme tokens and dark mode

**Why first:** every later step writes new markup. If tokens land first, that markup is
themeable for free.

**Files:** `dashboard/src/styles.css`, `dashboard/src/App.jsx`,
`dashboard/src/components/Sidebar.jsx`

- `styles.css` already declares the palette in `:root`. Add a second block
  `body[data-fw-theme="dark"]` overriding the same custom properties. Values are in
  the prototype's `<helmet><style>`. Warm dark, not cool grey — the light palette is
  warm and a cool dark clashes (this is the reason the note at the top of `styles.css`
  says dark mode was dropped last time).
- Three colours in the light palette do double duty and need their own tokens so dark
  mode does not invert them wrongly:
  - `--fw-invert` / `--fw-on-invert` — the `button.dark` pair (`#33312C` bg on
    `#F7F5F1` text). In dark mode this flips to light-on-dark.
  - `--fw-on-accent` — white text/glyphs sitting on `--accent`. Dark mode uses a very
    dark green here, because dark-mode sage is lighter than light-mode sage.
- Audit for hard-coded hexes outside `:root`. Known offenders: `.meter.warn > span`
  (`#C08A3E`), `.meter.over > span` (`#B4503F`), `button.text.danger` (`#B4503F`),
  `.avatar` (`#E9E5DC`), `.minibar` / `.costbar` track (`#E9E5DC`), `.blocker`
  (`#E8D9B8` / `#FBF3E4` / `#6B5326`), `.maintenance` (same family),
  `.archive-note` border (`#D9D4C8`), `.oauth-mark.grid` swatches. Each becomes a token.
- Toggle: two-button Light/Dark segmented control at the bottom of the sidebar, above
  `.sidebar-foot`. Sets `data-fw-theme` on `<body>`. Persist in `localStorage` under a
  key you own; default to `light` (do **not** default to `prefers-color-scheme` on the
  first release — the light theme is the researched one).

**Do not break:** printing, the `prefers-reduced-motion` spinner rule, `.chip.inferred`'s
dashed border being visibly different from `.chip.strong`'s solid fill in *both* themes.

---

## R1 — Fold the welcome/invite box into the walkthrough

**Files:** `App.jsx`, `components/JoinOrg.jsx`, `components/Tutorial.jsx`,
`pages/Settings.jsx`, `components/Organization.jsx`

Today `JoinOrg` renders *above* `Tutorial` as a separate card, and only when `untouched`
is true (`App.jsx` — signed in, no funders, no programs, no key). Two problems the user
named: it reads as a stray box, and an existing user can never redeem a code.

- Delete the `{state && page === "dashboard" && untouched && <JoinOrg …/>}` branch from
  `App.jsx`, and the `untouched` / `startedFresh` state with it.
- Move `JoinOrg`'s content into `Tutorial`'s **step 1** (`KeyStep`), above the API-key
  copy: heading, the code input, "Join my colleague", and the "No code? Carry on below"
  line. `KeyStep`'s `done` condition is unchanged (`state.key_available`).
- On success, `api.org.join()` already moves the person. Call `onChange()` then jump
  straight to the last step (or close the walkthrough) — they inherit a configured org
  and should not be walked through configuring it. Read `onboarding_done` from the org
  they just joined; if it is true, close.
- **New:** a "Join another organization" panel in `Settings.jsx`, below `Organization`.
  Same `api.org.join` call, no `untouched` gate. The confirm must state what is left
  behind — joining *moves*, it does not merge (the comment in `JoinOrg.jsx` is the
  authority here). Server side: check whether `POST /api/org/join` refuses a user whose
  org has data. If it does, decide deliberately — either allow it and keep the old org's
  rows orphaned but recoverable, or keep refusing and tell the user why in the dialog.
  Do not let the button 500.

**Do not break:** `JoinOrg`'s uppercase-as-you-type behaviour, or the fact that a code is
single-use and two-week expiring.

---

## R2 — Themed dialogs instead of `window.confirm` / `window.prompt`

**Files:** new `components/Confirm.jsx`, then `components/Funders.jsx`,
`components/Programs.jsx`, `components/Organization.jsx`, `pages/Settings.jsx`,
`pages/Discover.jsx`

Every destructive path currently uses a browser dialog. Full list to migrate:

| Where | Call today |
|---|---|
| `Funders.jsx` `toggle()` | `window.prompt` — "why are you taking them off?" |
| `Funders.jsx` `remove()` | `window.confirm` |
| `Programs.jsx` `remove()` | `window.confirm` |
| `Organization.jsx` `drop()` | `window.confirm` — remove a member |
| `Organization.jsx` `handOver()` | `window.confirm` — transfer admin |
| `Settings.jsx` `KeyPanel.remove()` | `window.confirm` — delete the saved key |
| `Discover.jsx` `SharedFunders.report()` | `window.prompt` — report reason |

- Build one `<Confirm>`: `{ open, tone: "sage" | "clay", icon, title, body, points[],
  cancelLabel, confirmLabel, onConfirm, onCancel }`. Centered, `role="dialog"`,
  `aria-modal`, focus trapped, Esc cancels, click-outside cancels, confirm button focused
  last. The `points[]` array is what makes these better than the browser: the prototype
  uses it to say *what actually happens* rather than "are you sure?".
- The two `prompt`s become a `<Confirm>` with one text field. Keep the prefilled default
  `"We already receive funding from them"` for the pause reason.
- Keep the confirmations' existing wording — it is careful, and it is the product's
  voice. Do not shorten it into "Are you sure?".

**Do not break:** the typed-email guard on Close Account (`Settings.jsx`
`DeleteAccount`). That is deliberately *not* a confirm dialog — two buttons three pixels
apart is what it exists to avoid. Leave it as a typed field.

---

## R3 — Program cards as a chip row at the top of This week

**Files:** `pages/Dashboard.jsx`, `components/Programs.jsx`

- Move `<Programs>` from the bottom of `Dashboard.jsx` to directly under the page header,
  above the stage boxes. Delete the now-single-child `.paircols` wrapper.
- Rewrite `Programs` as a wrapping row of chips instead of `.progrow` rows. Each chip is
  a flex container with **two** children — a tick button (mark + name) and a pencil
  button, separated by a hairline. Do not nest a button inside a label; `Programs.jsx`
  already carries a comment about why that broke.
- **An empty card cannot be ticked.** `Programs.jsx` already computes
  `const empty = !program.summary && program.keywords.length === 0`. Use it: the chip
  renders dashed with a clay "needs filling in" tag, and clicking it opens the editor
  instead of toggling `active`. Also guard the server call — `PUT /api/programs/:id`
  should refuse `active: true` on a card with no summary and no keywords, so the rule
  holds if someone hits the API directly.
- Removing a program moves inside the editor ("Remove this program", bottom-left) behind
  the R2 dialog. Keep the existing copy: removing a card does not delete what it found.
- Keep the `drafted_by_ai && !reviewed_by_human` → "AI draft — review it" marker. It is
  the same §6 rule as `.chip.inferred`.

---

## R4 — Three stage boxes replacing the run log

**Files:** `pages/Dashboard.jsx`, new `components/Stages.jsx`, new
`components/StageDetail.jsx`, `components/RunLog.jsx`, `app/` run serialisation,
`agent/run.py`

This is the largest step and the only one that needs new data from the server.

**UI:** three cards above the findings, one per tier, visually distinct (dashed/paper for
the free filters, sage for triage, white-with-clay for scoring). Each shows the count that
passed, a footer line, and an "Engine" row. Clicking a card opens a modal: came in / went
through / set aside / cost, one paragraph on why things passed, then a list of reject
reasons. **Each reason expands** to the funders it set aside — name (linked to the page),
page title, and the specific detail for that page. A "Show the other N" button reveals the
rest.

**Data required.** `run.rejected_by_filter` is a `dict[reason → count]` (`agent/models.py`
`to_dict`) — enough for the totals, not enough for the drawers. Add a per-candidate reject
log:

```
rejects: [{ stage: 1|2|3, reason: str, funder: str, title: str, url: str, detail: str }]
```

- Stage 1 rows come from `FilterResult.detail`, which `agent/filters.py` already
  populates (`"$4,000 < $10,000"`, the ISO deadline, the matched title fragment).
- Stage 2 rows come from `triage()`'s second return value — `agent/score.py` line ~483
  already returns the model's ≤15-word reason and currently logs it and drops it.
- Stage 3 rows: score + the `verify.py` outcome when a claim was stripped.
- Cap the list (a few hundred rows) and paginate server-side if a run ever exceeds it.
- Cost per stage: `Budget.by_model` (`agent/score.py`) already tracks spend per model.
  Expose it as `usd_by_stage` so box 2 and box 3 can show their own cost.

**Run log:** keep `RunLog.jsx` verbatim, moved behind a "Show the technical log"
disclosure. It is still the only place a partial/error run explains itself.

**Do not break:** the log must stay visible-on-demand *while a run is going*, and the
stage boxes must not be the only surface — a run that dies mid-stage still needs the raw
output.

---

## R5 — Model choice per stage, and other providers

**Files:** `pages/Settings.jsx`, `agent/score.py`, `app/` settings schema + secrets,
`components/Stages.jsx`

- `agent/score.py` hard-codes `TRIAGE_MODEL = "claude-haiku-4-5"` and
  `SCORING_MODEL = "claude-sonnet-4-6"`, with a `PRICING` table keyed by those two
  strings. Make both settings: `triage_model`, `scoring_model`. **`PRICING` must gain an
  entry for every selectable model** — `Budget.check()` does `PRICING[model]` and will
  `KeyError` on an unknown one, which would abort the run.
- UI: the Engine row on boxes 2 and 3 opens a small picker dialog (three options, the
  recommended one chipped — Haiku for triage, Sonnet for scoring). Box 1 shows
  "Plain rules", greyed, so all three boxes line up. Do not put the picker inside the
  stage-detail modal; that panel is for what happened.
- Guard the choices: Opus at scoring will blow a $1 run budget on a large list. Show the
  projected cost in the picker, and let `Budget` stop the run as it already does rather
  than adding a second mechanism.
- **Other providers** (OpenAI / DeepSeek / Qwen): new "Which AI it uses" panel in
  Settings listing providers, each connected or offering "Add a key". Server work:
  a provider column on the stored key, one adapter interface with `messages.create`-shaped
  input/output, per-provider pricing, and `resolve_api_key` returning a provider +
  key pair. `SONNET_CACHE_MIN_TOKENS` and the `cache_control` marker are
  Anthropic-specific — skip prompt caching on other providers rather than faking it.
  Encrypt every provider's key the same way; no endpoint returns any of them.

**Do not break:** `--no-llm` still has to run free with no key, and
`FUNDWORTHY_STRICT_CONFIG` must still refuse to start on a half-configured install.

---

## R6 — Live spend

**Files:** `agent/run.py`, `app/` run state, `useRun.js`, `components/StatusStrip.jsx`

Today the strip shows `run.usd_spent`, which is only written when the run finishes, so it
reads $0.0000 for ten minutes and then jumps. `Budget.record()` (`agent/score.py`) already
computes the running total on every call.

- Flush `budget.spent_usd` (and `by_model`) to the run row after each `record()`, or push
  it onto the in-memory run state `GET /api/runs/current` reads.
- `useRun.js` polls every 1500ms already — no client change needed beyond reading the new
  field. If it feels steppy, interpolate in the UI; do not poll faster.
- Four decimals stay. The comment in `StatusStrip.jsx` explains why `$0.00` is unacceptable
  on a page whose job is to be trusted with a budget.
- Same live number feeds the per-stage cost in R4's boxes.

**Do not break:** `.costbar` stays always-visible and non-collapsible (§8).

---

## R7 — Discover funders: marketplace, pagination, blacklist

**Files:** `pages/Discover.jsx`, `components/Funders.jsx`, `app/` funders API

**7a — Marketplace at the top.** Collapse `StarterLists` and `SharedFunders` into one
compact section, first on the page, with a segmented tab: **Near you** (researched lists,
`api.directory.read`) and **Shared** (`api.directory.shared`). Small cards in a grid, not
stacked rows. On the Shared tab add a contribute strip — "Share the funders you add",
wired to the existing `share_funders` setting (`Settings.jsx` `ShareFunders`), which then
becomes read-only there or is removed from Settings entirely. Keep the report flag per
card and the "we have not researched these" caveat under the grid; that sentence is a §8
requirement, not garnish.

**7b — Pause vs blacklist vs delete.** Today unticking sets `active: false` and "Remove"
deletes the row — which reads backwards, as the user said. Three distinct actions:

| Action | Meaning | Reversible |
|---|---|---|
| Tick off (pause) | Stays on the list, greyed, not fetched. Costs nothing. | Yes, one click |
| Block | Moves to the blacklist. Never fetched, never suggested again. | Yes, "Put back" |
| Delete | Row and notes gone. | No |

- Pause = `active: false` (existing behaviour, existing `exclude_reason`).
- Blacklist needs a new flag — `blocked` — because it must also suppress the funder in the
  researched-list import and the shared directory. `app/db.py` already seeds a
  remove-list matching on funder name *and* page title; reuse that matcher so a single
  named program can be blocked without blocking the whole funder.
- Delete is not a per-row button any more. A "Delete several" mode turns the ticks into
  selection checkboxes; one confirm deletes the batch. This is the only place delete
  lives.

**7c — Pagination and search.** Replace `showAll` / "Show all 61 →" with 7 rows per page
(make the number a constant), a page indicator, prev/next, and numbered pages. Add a
name search above the list that filters before paging; when it matches nothing, offer
"Add it by hand". Server-side paging only if the list grows past a few hundred — 61 rows
filter fine on the client.

**7d — Blacklist collapsed.** Its own collapsed section, count in the header, opens on
click. Each row offers "Put back" (returns it to the list, paused).

---

## R8 — Search settings, compacted

**Files:** `components/SearchSettings.jsx`, `app/` settings schema, `agent/` sector use

- **Remove the "Where to look" sector checkboxes.** They are our guess at categories and
  the copy admits it. Keep `sectors_active` in the schema and in the API so old rows still
  read back; stop rendering the control. Check `agent/` for anything that *filters* on it
  before removing — if the pipeline narrows by sector, that behaviour must move to
  "which funders are on your list", which is where the geography filter already went
  (see the long comment in `agent/filters.py`).
- Keep, unchanged: "Also look beyond the funders on my list" and "Search automatically
  every week" plus the day/hour/timezone row.
- Shrink the panel: four numeric fields on one grid, hints moved to `title` tooltips, the
  two switches and Save on a single footer row. Roughly a third of the current height.

---

## R9 — Settings: member actions and the spending cap

**Files:** `components/Organization.jsx`, `styles.css`, `app/` settings

- "Make admin" and "Remove" currently sit in a `.row` with `gap: 4px`. Separate them: a
  labelled pill for Make admin, a wide gap, a hairline divider, then Remove as an
  icon-only clay button with an `aria-label`. Both keep the R2 dialogs, and both keep
  their server checks.
- Add "Change the monthly limit" beside the spend meter: quick amounts plus a typed
  figure, saved to the org's `cap_usd`. State plainly that the user's own Anthropic limit
  still applies on top — `Organization.jsx`'s header comment explains why we can only
  report our own spend and must never invent a credit balance. Turn the meter amber past
  80% (`.meter.warn` already exists).

---

## R10 — Icons over prose

**Files:** all of `dashboard/src/components/`, `pages/`

The audience has no technical background; the current UI explains itself in paragraphs.

- Replace repeated text buttons with a 16px stroke icon plus `title` **and**
  `aria-label`: Edit (pencil), Block (slashed circle), Delete (bin), Pause (two bars),
  Copy, Download CSV, Search, Add.
- Keep text on anything destructive-and-rare or unfamiliar: "Make admin", "Share mine",
  "Search again now", "Put back".
- One inline SVG sprite or a tiny `<Icon name>` component. No icon font, no icon package
  — `styles.css` notes there is no image asset anywhere in this app and it is worth
  keeping that true.
- Cut standing explanatory paragraphs to one line plus a tooltip. The first-run `.helper`
  banner already exists for orientation; use it rather than repeating context on every
  panel.

---

## R11 — Responsive

**Files:** `styles.css`, `components/Sidebar.jsx`

Breakpoints already in the file: 900 (sidebar), 880 (`.paircols`, landing), 760
(`.funder-row`), 700 (`.page` padding), 620 (`.opp-row`). Standardise on **900** and
**620** and fix what the redesign adds:

- `.page` padding to 18px and top padding to clear the fixed menu button.
- Stage boxes stack vertically under 900; the connector arrows are hidden, not rotated.
- Program chips wrap (they already do) — make sure the pencil stays a 44px-tall target.
- `.page-head` stacks; the CSV and Search buttons go full-width side by side.
- Status strip wraps to two lines with the spend and its bar kept on one line together.
- Funder rows: name and host on line one, actions right-aligned on line two. The
  `.funder-list.compact` grid-area trick already does this — reuse it, do not rebuild it.
- All dialogs: `max-height: 86vh`, internal scroll, sticky header, 20px page margin.
- Every tap target ≥ 44px on touch, including the row icon buttons.

---

## Verification checklist

Run these after each step, not at the end:

- `python -m pytest tests/ -q` — offline, no key. `tests/calibration.py` is the ranking
  test; a UI change must not move it.
- `python -m agent.run --no-llm` — still free, still $0.00.
- A run with a key: stage counts in the boxes must equal `rejected_by_filter` totals, and
  the live spend must land on the same figure the finished run reports.
- Both themes, both breakpoints, on: first-run walkthrough, empty dashboard, dashboard
  mid-run, dashboard with findings, Discover with 0 / 7 / 61 funders, Settings as admin
  and as a non-admin member.
- Keyboard only: every dialog opens, traps focus, closes on Esc, and returns focus to the
  control that opened it.
- An AI-inferred value and a sourced value still look different in dark mode.
