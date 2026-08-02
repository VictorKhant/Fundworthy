# Dashboard

Read-only run history for the RISE funding agent. (CLAUDE.md §4, §12 Block 4)

It answers three questions and deliberately nothing else: **is the agent on, what has
it cost, and what happened on each run.** No accounts, no login, no settings — §3 rules
those out for v1, which removes the entire OAuth surface. Config lives in the `Config`
tab of the Sheet, where Mauri already knows how to edit it.

## Run it locally

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173
```

With no credentials set you get the honest "not connected to a Sheet yet" state,
which is what the deployed page shows until the Sheet exists.

`npm run dev` mounts the real `api/runs.js` handler as dev middleware (see
`vite.config.js`), so local and deployed behave the same — Vite alone knows nothing
about Vercel functions and every fetch would fail.

## Deploy

Vercel, root directory `dashboard/`. Two environment variables:

| Variable | Value |
|---|---|
| `RISE_SHEET_ID` | The id in the Sheet URL |
| `GOOGLE_SHEETS_CREDENTIALS` | The whole service-account JSON, pasted in |

Same service account as the agent. It needs only read access here.

## Why there is a serverless function at all

A purely static page would have to make the Sheet **public** to read it, exposing
everything on it. Instead `api/runs.js` reads it server-side with the service account
and returns only run history and settings. The Sheet stays unpublished.

The function is read-only by construction: the OAuth scope is
`spreadsheets.readonly`, only the `Runs` and `Config` tabs are requested, and there is
no write path or POST handler in the file. Non-GET returns 405.

## The security tradeoff, stated plainly

§3 rules out auth for v1, so **this endpoint is unauthenticated**. Anyone with the
deploy URL can read the run history. That is an accepted tradeoff, not an oversight:

- It exposes run metadata and Config values — no credentials, and nothing beyond what
  is already in a Sheet Mauri shares with her team.
- `X-Robots-Tag: noindex` and a `<meta name="robots">` tag keep it out of search
  results.
- **Treat the deploy URL as the secret.** Share by link, not publicly.

If RISE ever wants this locked down, Vercel's built-in password protection is the
smallest change — it needs no code and keeps §3's "no auth code we maintain" intact.

## Files

| | |
|---|---|
| `api/runs.js` | Serverless function. Reads the Runs and Config tabs. |
| `src/App.jsx` | The whole UI. One file on purpose. |
| `src/styles.css` | Light and dark, no framework |
| `vercel.json` | Build config and security headers |

## Verified

- `npm run build` succeeds (~146 kB JS, 47 kB gzipped)
- Unconfigured → clean `200` with `configured: false`, not an error
- `POST` → `405`, endpoint is read-only
- Malformed credentials → `502` with a generic message; the credential and stack are
  logged server-side, never returned to the browser
- Both states rendered in a real browser — see `evidence/screenshots/`

**Not verified:** it has never read a real Google Sheet, and it has never been deployed
to Vercel. The populated screenshot uses fixture data through a temporary local stub
that was reverted; it proves the layout renders, not that the data path works.
