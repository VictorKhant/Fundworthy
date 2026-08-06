# Fundworthy — UI changes, round 2

The last roadmap described changes in the abstract and the implementation reasonably
interpreted them. This one is a **diff**: what is in `VictorKhant/Fundworthy@main` today
versus the prototype (`Fundworthy.dc.html`), and what to change so the app matches it.

Read as: *current* → *target*. Every item names the repo file to edit. Where the repo's
version is genuinely better than the prototype, it says so and says keep it — those are
marked **KEEP**.

Synced against `c093ef5c801c`.

---

## 0. Things the prototype does not show — do not delete them

The prototype is a design mock built from an earlier snapshot. It has no equivalent for
these, and their absence is not a request to remove them:

`OrgPanel` (org name + city), `ShareFunders` (the Settings-side sharing panel with the
check results), `ReportQueue`, "Turning it off", "Where your data lives", `DeleteAccount`'s
typed-email guard, `MaintenanceBanner`, `blockers` on the dashboard, the `enabled` recovery
notice, `schedule_day`/`hour`/`timezone`, `source_health`, `Spinner`/`Busy` everywhere,
`api_key_source === "environment"` notices, `stranded` handling in `JoinAnotherOrg`.

Same for anything in `agent/`. Nothing below needs a pipeline change.

---

## 1. Theme tokens

**KEEP the repo's `--muted`.** The repo has `#747065`; the prototype has `#8A8578`.
The prototype's is roughly 3.5:1 on `--panel` and fails AA for body text at 12–13px, which
is the size most of it is used at. The repo's value is the fix, not a drift.

Two real differences:

| Token | Repo | Prototype | Do |
|---|---|---|---|
| `--on-accent` (light) | `#F7F5F1` | `#FFFFFF` | **KEEP repo.** Paper-on-sage is the warmer read and matches the rest of the palette. |
| `--dash` (dark) | `#6E6759` | `#514D45` | Prototype's is dimmer. **KEEP repo** — the dashed AI-inferred border must stay visible in dark mode, and that is §6. |

Everything else in `:root` and `body[data-fw-theme="dark"]` already matches. No work here
beyond confirming the three above are deliberate.

---

## 2. Sidebar — `components/Sidebar.jsx`

**Nav items have no icons.** The prototype puts a 16px stroke glyph before each label,
sized `width:17px` in a flex slot at `opacity:.8`, gap 10px. Add to `PAGES` and render
through the existing `Icon` component (all four paths need adding to `Icon.jsx`'s `PATHS`):

- This week — `M2.5 8.5 8 3l5.5 5.5M4 7.8V13h8V7.8` (house)
- Past findings — `M2.5 5.5h11v7.5h-11zM2.5 5.5 4 3h8l1.5 2.5M6.5 8.5h3` (archive box)
- Discover funders — `M7 11.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9ZM10.4 10.4 14 14` (magnifier)
- Settings — a **toothed cog with a hollow centre**, not a radial burst (see §2a)

This is the one place R10 went the wrong way: it turned row actions into icons but left the
nav as an undifferentiated column of four text links, which is the list a non-technical user
scans most often.

### 2a. Three icons that must not be the same glyph

The app now has three controls whose obvious first draft is "a circle with rays or spokes",
and drawn that way any two of them are indistinguishable at 14–16px. They are different
things and need different silhouettes:

| Control | Where | Glyph |
|---|---|---|
| **Light** theme | `ThemeToggle.jsx` | Sun — small circle, eight straight rays. Already correct. **KEEP.** |
| **Settings** nav | `Sidebar.jsx` / `Icon.jsx` | **Cog** — an eight-tooth gear outline with a hollow centre. A ring of *trapezoidal teeth*, not spokes. |
| **Adjust search settings** | `StatusStrip.jsx` | **Sliders** — two horizontal rails with a knob on each, offset from one another. |

The cog path (16×16 viewBox, `fill="none"`, `stroke="currentColor"`, `stroke-width="1.5"`,
`stroke-linejoin="round"`), eight teeth on r=6.6/5.0 about centre (8,8):

```
M14.4 6.4 14.4 9.6 12.9 9.2 12.3 10.6 13.7 11.4 11.4 13.7 10.6 12.3 9.2 12.9
9.6 14.4 6.4 14.4 6.8 12.9 5.4 12.3 4.6 13.7 2.3 11.4 3.7 10.6 3.2 9.2
1.6 9.6 1.6 6.4 3.2 6.8 3.7 5.4 2.3 4.6 4.6 2.3 5.4 3.7 6.8 3.2
6.4 1.6 9.6 1.6 9.2 3.2 10.6 3.7 11.4 2.3 13.7 4.6 12.3 5.4 12.9 6.8Z
M8 5.7a2.3 2.3 0 1 0 0 4.6 2.3 2.3 0 0 0 0-4.6
```

The sliders glyph:

```html
<path d="M2.5 4.5h4M9.5 4.5h4M2.5 11.5h1.5M7 11.5h6.5" />
<circle cx="8" cy="4.5" r="1.7" /><circle cx="5.5" cy="11.5" r="1.7" />
```

Why sliders rather than a second gear: that button opens four numeric values you tune —
an award floor, a runway, a result cap, a spend ceiling — and it sits two panels away from
the Settings nav item. Two gears on one screen meaning different destinations is the
problem this split exists to avoid. Add both to `Icon.jsx`'s `PATHS` as `cog` and
`sliders` so no third caller can reinvent either.

**Org chip.** Prototype renders a 26px `border-radius:8px` square holding the org's first
initial (`--accent` on `--accent-soft`, 13px/700) to the left of the name, inside a
`--card` pill with a `--line` border. Check `OrgSwitcher.jsx` against that.

---

## 3. This week — `pages/Dashboard.jsx`

### 3a. Page order

Current:

```
head → helper → Programs → blockers → StatusStrip → outcome → knobs → Stages → log → Findings
```

Target:

```
head → Programs → blockers → StatusStrip → knobs → Stages(+log link) → log → outcome → Findings
```

Two moves:

1. **The outcome line goes directly above "Worth a look".** It is currently rendered inside
   `StatusStrip`, immediately under the strip. It belongs against the list it explains —
   "Checked every funder on your list · skipped 12 you have already seen" is the answer to
   *why is this list short*, and that question is asked at the list, not four sections
   above it. Lift it out of `StatusStrip.jsx` into `Dashboard.jsx` as its own element
   placed just before `<Findings>`; keep `STOP_REASONS` and the `attention` tone exactly
   as they are.

2. **The helper banner is not in the prototype.** It is dismissible and low cost, so this
   is a judgement call — but it sits between the page head and the programs row, which is
   where the eye lands first, and it explains a convention (the AI/sourced split) that the
   findings already mark inline. Suggest: drop it, or move it below `<Findings>`'s heading
   so it annotates the thing it describes.

### 3b. Stages are hidden during a run — they should be the run

`Dashboard.jsx` renders `<Stages>` only when `!isRunning && state.latest_run`. The comment
says last week's funnel above a live log would read as this run's progress — correct
problem, wrong fix. The prototype's answer is to make the boxes *show* the live run, which
is the entire reason they were asked for:

- Keep them mounted while `isRunning`.
- Feed them the live counters from `useRun`'s `live` payload rather than `latest_run`.
- The stage currently working: `transform: translateY(-3px)` and
  `animation: fw-pulse 1.4s ease-in-out infinite`
  (`@keyframes fw-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(76,122,94,.28) } 55% { box-shadow: 0 0 0 9px rgba(76,122,94,0) } }`).
- Finished stages `opacity:.8`; not-yet-reached `opacity:.55`.
- A 3px progress rail at the bottom of each card (`border-radius:99px`, track `--track`,
  fill `--muted` / `--accent` / `--clay` by stage), width = that stage's completion,
  `transition: width .12s linear`. Hidden entirely when not running.
- Between the boxes, a `5px` `--accent` dot animating left-to-right along the connector
  while that stage is live:
  `@keyframes fw-flow { 0% { transform: translateX(-10px); opacity: 0 } 35% { opacity: 1 } 100% { transform: translateX(16px); opacity: 0 } }`.

This needs the run state to expose per-stage progress. R6 already flushes `budget.spent_usd`
mid-run; add the three counters (`candidates_parsed`, `triaged`, `scored`) to the same
flush and the boxes fill themselves.

### 3c. Stage boxes need a section header

There is no heading above `.stages`, and the log is a separate `<details>` further down.
The prototype puts one row above the grid:

- left: `HOW THIS WEEK'S LIST WAS MADE` — 12px, `text-transform:uppercase`,
  `letter-spacing:.08em`, `--muted`, 600
- right: "Show the technical log" as a `--accent` text button with a small terminal glyph
  (`M4 5.5 6.5 8 4 10.5M8.5 11h4`)

The `<details>`/`<summary>` becomes a controlled disclosure driven by that button, opening
in place below the grid. Keep `open={isRunning}` behaviour.

### 3d. Stage card anatomy

Current card (`Stages.jsx` + `.stage*`):

```
Step 1
Read and filtered
23 of 61
38 set aside
Engine  Plain rules            $0.00
```

Target:

```
[1]  Free filters                    ●
23
worth full scoring
────────────────────────────
of 61 read                      Why ›
```
…with the engine row as a **separate button below the card**.

Specifics:

- **Numbered badge, not a "Step N" eyebrow.** 22px square, `border-radius:7px`, 12px/700,
  filled: stage 1 `--nav-active`/`--muted`, stage 2 `--accent`/`--on-accent`,
  stage 3 `--clay`/`--on-accent`. Sits inline-left of the title.
- Title 13px/600, `letter-spacing:.01em`. **Rename**: "Free filters", "Quick read",
  "Full scoring" (repo: "Read and filtered", "Quick look", "Read properly").
- A status dot on the right of the title row: 8px circle, `--accent` when that stage is
  live, `--dash` otherwise.
- **The big number is the pass count alone** — display face, 34px, `line-height:1.05`,
  `margin:12px 0 2px`, coloured `--fg` / `--accent-deep` / `--clay-deep` by stage. The repo
  renders `23 of 61` at one size, which makes the funnel unreadable at a glance.
- Under it, a 12.5px `--muted` label naming what the number *is*: "pages worth paying to
  read" / "worth full scoring" / "on your list this week".
- A 1px `--line-soft` divider, `margin:11px 0 9px`.
- Footer row: the denominator on the left ("of 214 checked · free", "of 61 read",
  "of 23 scored") and an `--accent` **"Why ›"** affordance on the right. The repo has no
  visible affordance at all — the card is clickable and nothing says so.
- Card: `border-radius:16px`, `padding:15px 17px`. Shells unchanged
  (dashed/panel, accent-soft, card+clay-line) except stage 3 gains
  `box-shadow: 0 6px 20px rgba(160,107,79,.07)`.
- Grid: `repeat(3, 1fr)` with **`gap:30px`** — the gap is where the connector arrows live
  (`position:absolute; left:-30px; top:52px`). Collapses to one column and drops the
  arrows under 900.

### 3e. The engine row moves out of the card

Currently inside `.stage`, holding `Engine | model | cost`. The prototype makes it a
sibling button under the card so all three line up on one baseline whatever the card
heights are:

- `margin-top:8px`, `padding:7px 11px`, `border-radius:10px`, `1px solid --line`,
  background `--card` (stages 2–3) or `--panel` (stage 1)
- `ENGINE` label — 10.5px, uppercase, `letter-spacing:.08em`, 700, `--muted`
- value 12.5px/600, `--fg`; stage 1 reads **"Plain rules"** in `--muted` with
  `cursor:default`
- a small chevron on the right, `--accent`, only on stages 2–3
- **The per-stage cost is not on this row.** It lives in the stage detail's figures. The
  repo shows `$0.0000` on the card, which puts four decimal places in a row of three cards
  and reads as noise; the number people want on the card is the count.

### 3f. Stage detail — `components/StageDetail.jsx`

Three differences, all in the body.

1. **The four figures are cards, not an inline row.** `.stage-figures` is currently four
   `<span><strong>N</strong> label</span>`. Target: a
   `repeat(auto-fit, minmax(120px, 1fr))` grid of bordered boxes, gap 10px, each
   `border-radius:12px`, `padding:12px 14px`, number in the display face at 26px:
   - came in — `--card` / `--line` / `--fg`
   - went through — `--accent-soft` / `--accent-line` / `--accent-deep`
   - set aside — `--clay-soft` / `--clay-line` / `--clay-deep`
   - spent — `--card` / `--line` / `--fg`, label "this step is free" on stage 1

2. **"Why it let those through" is missing.** The prototype has two labelled halves, and
   the repo only has the second. Above the reason list, add an uppercase 12px `--muted`
   heading `WHY IT LET THOSE THROUGH` and one sentence in a sage box
   (`--accent-soft` on `--accent-line`, `border-radius:11px`, `padding:11px 14px`), e.g.:

   - Stage 1 — "Every one of these named a grant, was open, was over your $10,000 floor,
     and had enough runway to write an application."
   - Stage 2 — "The model found language matching one of your ticked programs on the page
     itself."
   - Stage 3 — "Scored 55 or better on award size, program fit, effort and deadline
     runway — and every stated figure was found word-for-word on the funder's page."

   Then the existing list under `WHY IT SET THE REST ASIDE`. `PARAGRAPH[stage.n]` stays;
   it is doing a different job (it explains the step, not the pass rule).

3. **Reason rows.** Current: caret, name, count on the right. Target: caret, then the
   **count as a large `--clay` display numeral** (19px, `min-width:30px`, right-aligned,
   `tabular-nums`), then the label, then a 64×6px proportional bar on the right
   (`--track` track, `--clay` fill, width = `n / max`). The bar is what makes "64 below
   your floor, 13 faith-based" legible without reading the numbers. Open row gets a
   `--line-soft` background and the drawer below it matches.

   Inside the drawer: **the funder name is the link**, not the title —
   `{funder} ↗` in `--accent` at 13px/600, then the page title in `--body` 12.5px, then the
   detail in `--clay-deep` 12.5px, then the bare host in `--muted` 11.5px. The repo links
   the title and prints the funder as plain text, which buries the name people scan for.
   Show **3** before "Show the other N" (repo shows 5), and make that a bordered pill
   button rather than a text link, with a chevron that flips to "Show fewer".

### 3g. Model picker — `components/ModelPicker.jsx`

- **Header**: the stage's numbered badge (30px, same colours as the card) + title
  `Which model does {stage name}?` + sub-line "You can change this before any search." +
  a 32px ✕ close button top-right. Repo has a bare `<h2>` and a Close button at the foot.
- **Options are radios.** A 16px circle on the left — selected is
  `border:5px solid --accent` on `--card`, unselected `1px solid --dash`. Repo relies on
  `aria-pressed` plus an "In use" chip, which reads as a third badge rather than a
  selection state. Drop the "In use" chip once the radio is in.
- **Recommended chip** stays, right-aligned: `--accent-soft` / `--accent-deep`, 11.5px/600.
- **KEEP the projected cost.** The prototype has no equivalent and the repo's `~$0.0004`
  from `RATES` is better — it is the one thing that stops somebody picking Opus and
  silently truncating their run. Keep the "costs are from your last search" footnote too.
- Add the prototype's provider line under the options: "Add OpenAI, DeepSeek or Qwen under
  **Settings → Which AI it uses** and their models appear here too." — only once §5a exists.
- Picking closes the dialog. No footer Close button; the ✕ is the escape.

### 3h. Programs — `components/Programs.jsx`

**Wrap the chip row in a panel.** Currently `.progbar` is a bare row that floats between
the page head and the blockers with no boundary. Target: a `--panel` card,
`1px solid --line`, `border-radius:14px`, `padding:14px 16px`, containing:

- a header row: 24px sage icon square (checkmark glyph) + `What to search for` in the
  display face at 19px + `N of M being searched` in 12.5px `--muted`, and on the right an
  **`+ Add` pill** (`border-radius:999px`, `1px solid --line`, `--card`) — not the current
  text button at the end of the chip row, which wraps to a random position on a long list.
- the chips
- when any card is empty, a clay hint line under the row with a warning glyph: "A card
  with nothing in it can't be searched for — open it and paste the program's web page."
  The repo's note only covers the *nothing ticked* case; both are worth having.

**Chip mark.** Currently a text glyph (`+` / `✓` / empty) in `.progchip-mark`. Target: an
18px `border-radius:6px` square holding a stroke icon —
- ticked: `--accent` fill, `--on-accent` check
- unticked: `--card`, `1px solid --dash`, `--muted` plus-sign
- empty: no fill, `1px dashed --dash`, `--clay` ✕

The two-button split, the hairline divider, the `unfilled` modifier and the server-side
guard are all correct already. **KEEP.**

### 3i. Status strip — `components/StatusStrip.jsx`

- "Adjust search settings" gains the **sliders** glyph before the label (`--accent`, 14px)
  — see §2a; it must not be a gear.
- While a run is going, a **LIVE** marker after the spend figure: 11.5px, 600,
  `letter-spacing:.04em`, uppercase, `--accent`. Pairs with 3b — the number moving with no
  label on it reads as a glitch.
- The spend bar needs `transition: width .12s linear` so the live number animates rather
  than jumping between polls.
- Four decimals, the always-visible costbar, and the three-state `status-state` are all
  right. **KEEP.**

### 3j. Search settings — `components/SearchSettings.jsx`

Nearly there. One change: **both switches belong on the footer row.** "Also look beyond
the funders on my list" is currently a `.field.inline` on its own line above the foot,
which puts a full-width row between the knobs grid and the save row for a checkbox that is
off and disabled-in-spirit. Move it next to "Search automatically every week" in
`.searchpanel-foot`, `gap: 12px 20px`, `flex-wrap: wrap`, with Save pushed right by
`margin-left:auto`.

Keep the schedule sub-panel, the Undo button, and "Save settings" as the label — the
prototype says "Save" and is simply less complete.

---

## 4. Discover funders — `pages/Discover.jsx`, `components/Funders.jsx`

### 4a. The marketplace is a card grid, not stacked rows

The biggest visual gap on this page. `StarterLists` and `SharedFunders` render
`.directory-row`s — full-width rows, one per funder, name left and button right. With five
shared funders that is five full-width rows, and the section is taller than the funder list
it sits above.

Target: `display: grid; grid-template-columns: repeat(auto-fill, minmax(228px, 1fr)); gap: 8px`.
Each card `border-radius:12px`, `padding:11px 13px`, `1px solid --line` on `--card`
(a list already fully imported gets `--accent-soft` / `--accent-line`):

- row 1: 22px rounded icon square (pin for Near you, basket for Shared) + name (13.5px/600,
  ellipsised) + meta pushed right in 12px `--muted` ("34 funders" / "4 lists")
- row 2: the description or evidence line, 12px `--muted`, clamped to two lines with
  `-webkit-line-clamp: 2`
- row 3: `Add to my list` as a small pill, and on Shared a report flag icon button pushed
  right (`--muted`, hover `--clay-soft`/`--clay-deep`)

The "We have not researched these" caveat moves **under the grid**, Shared tab only, as a
`--muted` 12px line with a clay warning glyph. It is a §8 requirement — keep the wording
verbatim, just move it.

### 4b. Marketplace header

- `<h2>` reads **"Add funders"**, not "Find funders", and gains a 26px sage basket icon
  square to its left. ("Find funders" collides with the disabled "Find funders near you"
  card below, which is a different thing.)
- The segmented tabs carry counts: a small pill after each label —
  active `--accent-soft`/`--accent-deep`, inactive `--line`/`--muted`, 11px/600.
- A 12.5px `--muted` blurb under the header row, swapping with the tab.

### 4c. Contribute strip

Currently a `.contribute` checkbox label with three lines of prose. Target: a bordered
strip above the grid (`1px dashed --dash` when off, `--accent-soft` / `--accent-line` when
on), `border-radius:12px`, `padding:10px 13px`, holding:

- a 26px icon square (upload arrow when off, check when on)
- title + one-line note ("Share the funders you add" / "You are sharing N funders")
- a **`Share mine` button** (sage filled when off, outlined "Stop sharing" when on)
- a secondary **`Add one you know`** pill that opens the funder editor

Turning it *on* goes through the themed confirm, with the what-leaves/what-never-leaves
points — the same three bullets `ShareFunders` already has in `Settings.jsx`. A checkbox
that silently starts publishing rows is the one place on this page where a confirm earns
its keep.

### 4d. Section order

Current: Marketplace → FindMore → Funders(+blocklist).
Target: Marketplace → **Funders it watches** → **Blacklist** → FindMore.

"Find funders near you" is disabled and unbuilt; it currently sits between the two things
people came for.

### 4e. Blacklist is its own section, and is called that

`.blocklist` lives inside the `Funders` panel behind a `▸ Blocked — 3` text button. Target:
a sibling `<section>` after the funder panel, styled like the other cards
(`--panel`, `1px solid --line`, `border-radius:14px`), whose whole header is the toggle:

- a caret that rotates 90° on open (`transition: transform .18s ease`) — not a `▸`/`▾`
  character swap
- a 26px clay icon square (slashed circle)
- **"Blacklist"** in the display face at 20px — the word the user asked for; "Blocked" is
  the row chip, not the section name
- the count in 12.5px `--muted`
- `Show` / `Hide` in `--accent`, right-aligned

Open state gets a one-line explainer ("Never fetched, never read, never scored — and never
suggested to you again. Put one back and it returns to the list above, paused.") and rows
that are *not* the full `<Row>` component: 28px clay icon square, name, the reason in
`--muted`, and a `Put back` pill. A blocked funder has no tick, no edit and no sector to
show, so reusing `Row` renders four dead affordances per row.

Keep `blocked` as the flag name and the `Put back` semantics. **KEEP.**

### 4f. Funder list details

- **Search is always visible.** Currently gated behind `listed.length > PER_PAGE`. Style it
  as a bordered box (`1px solid --line`, `border-radius:11px`, `--card`) with a magnifier
  glyph inside on the left, a borderless input, and a ✕ clear button on the right when
  non-empty. Placeholder "Search a funder by name".
- **The tick is a button, not a native checkbox.** 26px, `border-radius:8px`; active =
  `--accent` fill with an `--on-accent` check; paused = `--card`, `1px solid --dash`, a
  `--muted` pause glyph. It carries the whole pause/resume affordance and a 13px system
  checkbox is both hard to hit and impossible to theme in dark mode.
- **Pager arrows are icon buttons**, not `← Previous` / `Next →` text: 30px rounded
  squares with chevrons, `opacity:.4` + `cursor:not-allowed` when at the end. Numbers stay.
  `.pager-num.on` becomes `--invert` / `--on-invert` rather than `--accent-soft` — sage is
  the "searched/good" colour on this page and using it for pagination reads as state.
- **Selection mode gets a banner.** When `selecting`, a clay strip above the list
  (`--clay-soft` / `--clay-line`) reading "Tick the ones you want gone, then press Delete
  them" / "N funders chosen", with the Delete and Cancel buttons in it. Currently the only
  cue is that the ticks silently change meaning.
- Selected rows tint `--clay-soft` with `border-radius:8px`.
- Sector moves under the name as `host · sector` in 12.5px `--muted`, rather than its own
  column — the column is empty space on every row at desktop width and collapses to an
  orphan at mobile.

The three-way pause / block / delete-several split, `PER_PAGE = 7`, filter-before-page, and
the confirm copy are all correct. **KEEP.**

---

## 5. Settings — `pages/Settings.jsx`, `components/Organization.jsx`

### 5a. "Which AI it uses" does not exist

The prototype has a provider panel and the repo has none — models are chosen per stage from
whatever `state.model_choices` offers, with no way to add a provider. R5 specified this and
only the per-stage half was built.

Target: a `panel raised` section after `KeyPanel`:

- lede: "Connect a provider here and its models become choosable on the three boxes on
  **This week**. You can mix them — a cheap model for the quick read, a stronger one for
  scoring."
- `repeat(auto-fit, minmax(230px, 1fr))` grid of provider cards: Anthropic (Claude),
  OpenAI, DeepSeek, Qwen
- each card: 26px initial square (`--accent`/`--on-accent` when connected, else
  `--nav-active`/`--muted`), name, a sage check when connected, the model list in 12.5px
  `--muted`, and `Add a key` / `Replace key` as a small pill
- connected cards sit on `--accent-soft` / `--accent-line`

The server work is the rest of R5 §"Other providers" — provider column on the stored key,
one adapter interface, per-provider pricing, `resolve_api_key` returning provider+key. If
that is not landing this pass, ship the panel with only Anthropic live and the other three
visibly disabled rather than absent; the point is that the model picker's "add a provider"
line has somewhere to point.

### 5b. Cap amounts — `Organization.jsx`

`CapEditor` offers `[10, 20, 50, 100]`. The prototype offers `[5, 12, 25, 50]`. The
prototype's set is right for the audience: the panel's own copy says a weekly search costs
about a dollar, so $10 is already three months of use and $100 is not a number anyone here
should be nudged toward. Change to `[5, 12, 25, 50]`.

Also: the amber threshold. `Meter`'s `tone` goes `warn` at `pct >= 80` — matches. **KEEP.**

### 5c. Member rows

`.member` has no avatar. The prototype puts a 30px `--track` circle with the person's
initials before the email. Small, but it is the only thing distinguishing three rows of
similar-length addresses at a glance.

`member-actions` — pill + divider + icon bin — is exactly right. **KEEP.**

### 5d. Invite code row

The prototype renders the code in a sage-tinted `<code>` (`--accent-soft` /
`--accent-deep`, `letter-spacing:.09em`, 15px) with the copy action as a 32px **icon
button**, then the expiry, then Cancel. The repo has plain `Copy` / `Cancel` text buttons.
Copy is a repeated action on a row — R10 says icon.

---

## 6. Confirm dialog — `components/Confirm.jsx`

The structure, the focus trap, the `points` array, the awaitable `useConfirm`, the
keep-open-on-error and the sage/clay tones are all right and are better than the prototype's.
**KEEP all of it.** One addition:

**An icon slot.** The prototype's dialogs open with a 40px `border-radius:12px` tinted
square holding a stroke glyph, to the left of the title — sage tint for ordinary
confirmations, clay tint for destructive ones. It is what makes a pause dialog and a delete
dialog distinguishable before reading a word, and at the moment the only difference between
them is the colour of one button at the bottom.

Add an optional `icon` prop (an `Icon` name), render it in a flex header alongside the
`<h2>`, and pass one from each call site: `pause` for pausing, `block` for blocking, `bin`
for deletes and member removal, `edit` for edit stubs, `add` for adds.

Dialog geometry to match: `max-width: 452px`, `border-radius: 18px`,
`box-shadow: 0 24px 60px var(--shadow)`, and the entry animation
`fw-pop .2s cubic-bezier(.2,.8,.3,1)` (fade + 10px rise + `scale(.985)`), scrim
`fw-fade .14s`. `StageDetail` and `ModelPicker` use `max-width: 600px` / `452px` with
`max-height: 86vh`, internal scroll, and a sticky header.

---

## 7. Responsive

Everything specified in R11 is in. Three things the new markup needs:

- The stage connector arrows must be **removed**, not rotated, under 900 — they are
  absolutely positioned into the grid gap and that gap does not exist in one column.
- The marketplace grid's `minmax(228px, 1fr)` gives one column under ~500px on its own; no
  media query needed, but check the card's row-3 buttons do not wrap under the meta.
- The funder search box, the selection banner and the pager all need to survive
  `.funder-list.compact`'s grid-area treatment at 620.

---

## Verification

Same checklist as R1, plus:

- Start a search and watch the three boxes: the live box lifts and pulses, the others dim,
  each rail fills, the dot travels the connector, and the spend ticks with a LIVE marker
  beside it.
- Open each stage box: four figure cards, a sage "why it passed" box, reason rows with
  proportional bars, a drawer whose first link is the funder's name, "Show the other N"
  expanding to the full set.
- Stage 1's engine row says "Plain rules" and does nothing when clicked; stages 2 and 3
  open the picker; the picker's radio, Recommended chip and projected cost all render.
- The sun, the cog and the sliders are visibly three different shapes at 14px, in both
  themes — the check is whether you can name each one without hovering it.
- Discover: marketplace is a grid of small cards on both tabs, blacklist is a collapsed
  section titled "Blacklist" below the funder list, and "Find funders near you" is last.
- Both themes on every dialog, and the dashed AI-inferred border still visibly differs from
  the solid sourced chip in dark mode.
