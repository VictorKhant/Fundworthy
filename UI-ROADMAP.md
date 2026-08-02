# Handoff: Fundworthy redesign of Rise-Fund-Finder

A phased roadmap for integrating the Fundworthy visual redesign + new screens (landing, login, org switcher) into the existing `VictorKhant/Rise-Fund-Finder` codebase **without breaking current functionality**.

## Overview

The repo today is a working local-first app: FastAPI backend (`app/`), agent pipeline (`agent/`), and a React dashboard (`dashboard/src/`) with three views (Dashboard, Archive, Settings) styled by one deliberately plain `styles.css`. Its own comment says "the visual pass comes later." **This is that visual pass**, plus a public landing page and account placeholders for a future hosted, multi-tenant version.

## About the design files

The `.dc.html` files bundled here are **design references built in HTML** — prototypes showing intended look and behavior, NOT production code to copy in. Recreate them inside the existing React app (`dashboard/`, Vite, no router, no CSS framework) using its established patterns: plain CSS in `styles.css` with CSS variables, function components, the `api.js` module. Do not introduce Tailwind, a component library, or a router — three views never justified one and still don't (landing/login can be two more page states or static files, see Phase 4).

## Fidelity

**High-fidelity.** Colors, type, spacing, radii and copy are final unless noted. Recreate pixel-perfectly.

## Design files in this bundle

| File | What it shows |
|---|---|
| `Fundworthy Landing.dc.html` | Public landing page (nav, hero + live-list mock, how it works, honesty principles, cost, footer) |
| `Fundworthy Login.dc.html` | Sign in / sign up card (toggles between modes; org name field on sign-up) |
| `Fundworthy App.dc.html` | Redesigned app: sidebar w/ org switcher, This week (status strip, collapsible search settings, simplified expandable findings, programs + funders side-by-side), Past findings, Settings w/ 3-step key walkthrough |
| `Current App (Recreation).dc.html` | Faithful copy of TODAY'S UI — the "before" reference. Use it to confirm feature parity. |

---

## THE PRIME DIRECTIVE — what must not break

These are correctness requirements from `dashboard/src/styles.css` header comments and `CLAUDE.md` §6. Every phase must preserve them:

1. **Inferred vs sourced values stay visually distinct.** Anything the AI judged (fit %, effort, prep time, score, funder type, service areas) carries a dashed border + visible "AI" mark. In the new theme: dashed `#C9C4B6` border chips and the dashed rule under the fit number. Never restyle these to look like sourced chips (solid, sage `#EDF2EE`).
2. **`needs_human_check` rows stay separate and last** ("Needs your eyes" section, clay-tinted border `#E8D9C8`), never hidden.
3. **Cost is always visible**: spend vs ceiling appears in the status strip on every visit (was `.costbar`). Keep the bar + "$X of $Y" text.
4. **"Not stated" never becomes a guess.** Keep muted "Amount not stated" / "Deadline not stated" chips.
5. **All existing API calls and behaviors keep working**: settings save, key save/test/delete, program CRUD + draft-from-link, funder CRUD + untick-with-reason, run start/stop + live log polling, archive months, CSV export URL (plain `<a download>` — keep it an anchor).
6. Keep accessibility affordances that exist: `aria-current` on nav, `aria-expanded` on the sidebar toggle, `role="img"` + label on the cost bar, `title` tooltips explaining AI marks.

## Design tokens (add to `:root` in styles.css)

```css
--bg: #F7F5F1;        /* warm paper */
--panel: #FCFBF8;     /* raised surfaces / sidebar */
--card: #FFFFFF;
--fg: #33312C;        /* ink */
--body: #55524A;      /* secondary text */
--muted: #8A8578;
--line: #E5E1D8;
--line-soft: #F1EFEA;
--accent: #4C7A5E;    /* sage — primary actions, sourced-good */
--accent-deep: #3A6149;
--accent-soft: #EDF2EE;  /* sage tint bg */
--accent-line: #D5E0D8;
--clay: #A06B4F;      /* secondary accent — warnings-lite, numerals */
--clay-deep: #9C5A34;
--clay-soft: #F5E9E0; /* urgent-deadline chip bg */
--clay-line: #E8D9C8;
--dash: #C9C4B6;      /* dashed borders on AI-inferred marks */
--nav-active: #EDEAE2;
--shadow: 0 18px 40px rgba(51,49,44,.06);
```

Dark mode: the current CSS has a `prefers-color-scheme: dark` block. Either derive equivalent warm-dark values or **drop dark mode for now** (acceptable; note it in the PR). Do not ship the old cool-gray dark palette with the new warm light one.

### Typography

- Display/headings + big numerals: **Newsreader** (Google Fonts; weights 400/500, italic 400/500). Self-host or `<link>` in `dashboard/index.html`.
- UI/body: **Albert Sans** (400/500/600/700). Base: 15px/1.6 in-app, 16px/1.6 on landing.
- Headline scale: landing h1 52px/1.12, section h2 34px, app page h1 30px, app section h2 19–21px, fit numeral 26px, all Newsreader 500, letter-spacing -0.01em.
- Chips 12–12.5px; helper/meta 13–13.5px; never below 12px.

### Shape scale

Cards/panels radius 14px (landing hero card 18px), inputs 10px, org switcher 12px, chips & buttons pill `999px`. Buttons: primary = sage bg, paper text, 500 weight; dark variant `#33312C` bg; secondary = white bg + `--line` border; ghost/text = sage text, no border.

---

## Roadmap — phases in order, each independently shippable

### Phase 0 — Safety net (do first)

- Run the app (`./start.sh`) and the tests (`python -m pytest tests/ -q`, 126 offline tests) to establish a green baseline. No test touches the dashboard, so UI regressions won't be caught by them — that's what the recreation file is for.
- Screenshot today's three views (or open `Current App (Recreation).dc.html`) as the parity checklist: every control there must exist after each phase.
- Work on a branch; the backend and `agent/` are **untouched** in Phases 1–3.

### Phase 1 — Retheme (pure CSS, zero markup changes)

Replace the values in `styles.css` `:root` with the tokens above; update fonts via `dashboard/index.html`; adjust the derived styles (button/pill radii, panel radius 14px, chip tints). Keep every selector name (`.chip.inferred`, `.opp.flagged`, `.costbar`, …) so all JSX keeps working.

- `.chip.inferred`: dashed `--dash` border, `--muted` text; `.chip-tag` becomes the small "AI" mark (`--line-soft` bg).
- `.chip.strong` (sourced amount): `--accent-soft` bg, `--accent-deep` text, 600 weight, no border.
- `.chip.warn` (urgent deadline / unverified): `--clay-soft` bg, `--clay-deep` text.
- `.opp.flagged`: full border `--clay-line` (replaces the 3px left border — the left-border-accent pattern is retired).
- `.opp-score`: Newsreader numeral, sage for clear rows, clay in the flagged section; keep the dashed underline + "fit · AI" tag.
- Buttons/inputs per shape scale.

**Exit check:** all three views render, nothing overflows, prime directives 1–4 visually intact.

### Phase 2 — Dashboard reorganization (JSX moves, no API changes)

Restructure `pages/Dashboard.jsx` to the layout in `Fundworthy App.dc.html`:

1. Header: "This week" + found-count subtitle + `Download spreadsheet` anchor + primary `Search again now` (calls existing `api.runs.start`).
2. Dismissible first-run helper banner (sage tint). Persist dismissal in `localStorage` key `fw.helperDismissed`.
3. **Status strip** (new component, extracted from RunPanel): researcher on/off dot, last-run stamp (keep `pacificStamp`), spend `$X of $Y` + mini bar, and a text-button `Adjust search settings` that expands…
4. **Collapsed settings panel**: the four knobs, sector checkboxes, beyond-partners + enabled toggles, Save. Same `draft`/`dirty` logic as today's RunPanel; while a run is active, swap the primary button to `Stop the search` and show the streaming log exactly as now.
5. Findings next (see Phase 3), "Needs your eyes" after.
6. Programs + Funders move to a 2-column grid at the bottom (`1fr 1fr`, collapsing to one column < 880px). Compact list styles per the mock; full editors (program draft-from-link, funder editor) open inside their card as today.

Keep `Dashboard.jsx` ordering logic (clear vs needs_check from `state`), `Programs.jsx`/`Funders.jsx` behavior intact — only their container/visuals change.

### Phase 3 — Simplified expandable findings

Rework `Findings.jsx` per the mock:

- Collapsed row: fit numeral block ("fit · AI", dashed rule), funder name + `Public database` chip when `source_kind === "indexed_database"`, title, then ≤4 headline chips: amount (or "Amount not stated"), deadline (urgent tint when `days_left < 21`), effort (AI-dashed), and `Unverified claim` when flagged.
- `More details` / `Less` toggle (component state, one open at a time is fine) reveals: score rationale ("Why it scored this way · AI"), prep time, time-to-funds, rank score (+" · provisional" when `section !== "scored"`), geography, program match, 990 link, source link, found date.
- **Every field currently rendered must still be reachable** — collapsed or expanded, nothing is deleted. Keep all `title` tooltips.

**Exit check:** with fixture data, diff against `Current App (Recreation).dc.html`: every chip/value there appears somewhere here.

### Phase 4 — Landing + auth placeholders (new, additive)

- **Landing**: static page per `Fundworthy Landing.dc.html`. Simplest safe integration: a static `landing.html` served by FastAPI at `/welcome` (or the Vite root with the app at `/app`). Copy in exact copy ("Your weekly grant researcher, for about a dollar.", "~$1 per weekly search / 10+ opportunities found / $0 subscription, ever", honesty bullets). The hero right card is a hand-built mock list — reuse real chip styles.
- **Login**: per `Fundworthy Login.dc.html`. **Placeholder only** — no real auth backend yet. Sign in/up toggle, email+password, disabled-or-stub Google/Microsoft buttons (neutral marks, NOT official brand logos, until a real OAuth integration adds proper branded buttons per provider guidelines), org name on sign-up. Route straight into the app on submit. Gate it behind a flag (e.g. `VITE_SHOW_AUTH=1`) so the local-first flow (`./start.sh` → straight to dashboard) is unchanged by default.
- **Org switcher** in sidebar: render from a stub `orgs` array with the active org; "+ Add an organization" opens nothing yet. Sidebar also gets wordmark ("Fundworthy" + clay dot), nav (This week / Past findings / Settings), user chip + Sign out (visible only behind the same flag).

### Phase 5 — Settings walkthrough + generalization sweep

- Settings per mock: 3-step plain-language key walkthrough, saved-key notice (sage tint, `…last4`), replace/remove/check controls — same `api.settings.*` calls and the three-state logic (saved / env / none) from today's `Settings.jsx`.
- New Organization panel (name + location inputs) — can write to a new `settings` field or stay visual-only for now; say which in the PR.
- **De-brand sweep**: replace hardcoded "RISE" strings in UI copy (`sidebar-brand`, "RISE funding finder", program placeholder URLs, `SECTOR_LABELS.warm_partner` → "Partners we already work with" is fine) with the org name from settings, defaulting to "Your organization". Keep the hackathon credit line in the footer. Grep targets: `RISE`, `risesandiego`, `Mauri`.
- Rename UI copy "the agent" → "the researcher" (copy decision from the design; backend names stay).

### Phase 6 (future, out of scope here)

Real accounts/multi-tenancy (backend work: per-org DB scoping, auth), Microsoft/Google OAuth, mobile nav drawer (below 880px the mock simply hides the sidebar and shows a top bar — a proper drawer is future work).

## Interactions & behavior summary

- Org switcher: click toggles dropdown (shadow `--shadow`, 12px radius); outside-click closes; active org highlighted `--line-soft`.
- Findings expand: instant or ≤150ms ease; no layout jump of neighboring cards.
- Status strip → settings panel expand/collapse via one text-button, label swaps "Adjust search settings"/"Hide search settings".
- Helper banner: Dismiss hides permanently (localStorage).
- Hovers: primary buttons darken (`--accent-deep`); bordered buttons darken border to `--dash`; nav rows tint `--nav-active`.
- Login mode toggle swaps heading/CTA/footer prompt and shows org-name field on sign-up.
- Landing nav anchors scroll to sections; all CTAs → login.

## Assets

No image assets. Fonts from Google Fonts (Newsreader, Albert Sans). The "logos" on OAuth buttons are intentionally neutral placeholders. Wordmark is text + a 6–7px clay dot.
