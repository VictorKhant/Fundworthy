# dashboard/

The React UI. Vite build, served by the FastAPI app in `app/` — **not** deployed
anywhere. See `docs/PLAN.md` §1 for why local, and `HANDOFF.md` → "If you deploy it"
for what has to change first.

> This used to be a read-only run-history page reading a committed `run.json`. `CLAUDE.md`
> §3 ruled out settings in the dashboard, so there were none. Both changed in v2 —
> the dashboard is now the control surface, and the reasoning is in `docs/PLAN.md` §0.

```bash
./start.sh              # from the repo root — builds this and serves it on :8000
./start.sh --dev        # + Vite dev server with hot reload on :5173
```

In dev the page runs on `:5173` and calls the API on `:8000`; in production both come
from `:8000` and requests are same-origin. That switch is the only environment-dependent
line in the front end (`src/api.js`).

## Layout

```
src/
├── App.jsx                 shell — collapsible sidebar, three views, no router
├── api.js                  every API call, plus shared formatting
├── styles.css              light/dark, deliberately plain
├── pages/
│   ├── Dashboard.jsx       run controls → programs → funders → findings
│   ├── Archive.jsx         findings by month
│   └── Settings.jsx        the API key
└── components/
    ├── RunPanel.jsx        weekly knobs, Re-run button, live log, cost bar
    ├── Programs.jsx        program cards + the "read this page for me" assistant
    ├── Funders.jsx         the partner list
    └── Findings.jsx        one finding, and the two-block reading order
```

No router library and no state library. Three views and one `/api/state` call do not
justify dependencies RISE would have to keep updated.

## Two things that look cosmetic and are not

**`.chip.inferred`** marks a value the AI judged rather than read off the funder's page
— funder type, service areas, fit confidence, the hours estimate. `CLAUDE.md` §6 forbids
stating a number that was not on a page we fetched, and a correctly-nulled field still
misleads if the page renders a guess right beside it without saying which is which. If a
redesign drops that distinction, the UI starts making claims the pipeline refuses to.

**The two-block order** — everything the agent is confident about first, everything
needing a human at the bottom — is what Mauri asked for directly. It is enforced in SQL
(`app/repo.py: list_opportunities`) so every surface agrees; the split here is
presentational only.

## Not built here

- No auth. The app is localhost-only, which is what makes that honest (`CLAUDE.md` §3).
- No editing of findings. The agent produces a ranked list; deciding is the human's job.
- No Google export UI yet. `sinks/sheets.py` can write a Sheet from the CLI.

`dashboard/public/run.json` is still written on every run as a static export, so the
built site also works opened directly with no backend. It carries the month's findings,
not just the last run's — otherwise a mid-week re-run that legitimately finds nothing new
would blank a page that should still show everything found so far (evidence E13).
