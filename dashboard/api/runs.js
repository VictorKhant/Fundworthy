// Vercel serverless function: read the Runs and Config tabs of the Sheet. (CLAUDE.md §5)
//
// This exists for one reason: it lets the Sheet stay unpublished. A purely static
// page would need the Sheet made public to read it, which would expose everything on
// it. Instead the service account reads it server-side and the browser only ever sees
// the rows below.
//
// Read-only by construction:
//   - the OAuth scope is spreadsheets.readonly
//   - only the Runs and Config tabs are requested
//   - there is no write path in this file, and no POST handler
//
// §3 is explicit that the v1 dashboard has no accounts and no auth. That is a
// deliberate tradeoff: this endpoint is unauthenticated, so treat the deploy URL as
// the secret and share it by link only. It returns run history and settings — no
// credentials, and nothing that is not already in the Sheet Mauri shares with her team.

import { JWT } from "google-auth-library";

const SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets";
const SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"];

// Serverless instances are reused between invocations; caching the client avoids a
// token round-trip on every request.
let cachedClient = null;

function credentials() {
  const raw = process.env.GOOGLE_SHEETS_CREDENTIALS;
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("GOOGLE_SHEETS_CREDENTIALS is set but is not valid JSON.");
  }
}

async function sheetsClient() {
  if (cachedClient) return cachedClient;
  const creds = credentials();
  if (!creds) return null;
  cachedClient = new JWT({
    email: creds.client_email,
    key: creds.private_key,
    scopes: SCOPES,
  });
  return cachedClient;
}

async function readRange(client, sheetId, range) {
  const url = `${SHEETS_API}/${encodeURIComponent(sheetId)}/values/${encodeURIComponent(range)}`;
  const { data } = await client.request({ url });
  return data.values || [];
}

/** [headers, ...rows] -> array of objects. Blank tab -> []. */
function toObjects(values) {
  if (values.length < 2) return [];
  const [headers, ...rows] = values;
  return rows
    .filter((r) => r.some((cell) => String(cell || "").trim() !== ""))
    .map((row) => Object.fromEntries(headers.map((h, i) => [h, row[i] ?? ""])));
}

function parseMoney(value) {
  const n = Number(String(value || "").replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

export default async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "This endpoint is read-only." });
  }

  // Runs change once a week. A short cache keeps us off the Sheets quota while
  // still reflecting a manual run within the minute.
  res.setHeader("Cache-Control", "public, max-age=60, s-maxage=300");

  const sheetId = process.env.RISE_SHEET_ID;

  try {
    const client = await sheetsClient();
    if (!client || !sheetId) {
      // Not an error — the dashboard is expected to exist before the Sheet does.
      return res.status(200).json({
        configured: false,
        reason:
          "Set RISE_SHEET_ID and GOOGLE_SHEETS_CREDENTIALS in the Vercel project to " +
          "connect this page to the Sheet.",
        runs: [],
        config: {},
      });
    }

    const [runValues, configValues] = await Promise.all([
      // Column range is deliberately wider than the Runs tab currently is. The sink
      // appends new columns on the right as the agent learns to report more, and a
      // range pinned to the exact width silently truncates them — the page keeps
      // rendering, just without the newest column, which is the hardest kind of
      // missing data to notice. toObjects() keys off the header row, so extra empty
      // columns cost nothing.
      readRange(client, sheetId, "Runs!A1:Z200"),
      readRange(client, sheetId, "Config!A1:C40").catch(() => []),
    ]);

    const runs = toObjects(runValues).reverse(); // newest first
    const config = Object.fromEntries(
      configValues
        .slice(1)
        .filter((r) => r[0])
        .map((r) => [String(r[0]).trim().toUpperCase(), String(r[1] ?? "").trim()]),
    );

    const spendToDate = runs.reduce((sum, r) => sum + parseMoney(r["Cost"]), 0);

    return res.status(200).json({
      configured: true,
      runs,
      config,
      totals: {
        runCount: runs.length,
        spendToDate: Number(spendToDate.toFixed(2)),
        lastRun: runs[0]?.["When it ran"] ?? null,
        enabled: (config.ENABLED ?? "TRUE").toUpperCase() !== "FALSE",
      },
    });
  } catch (err) {
    // Never leak the credential or the stack to the browser.
    console.error("runs endpoint failed:", err);
    return res.status(502).json({
      configured: true,
      error: "Could not read the Sheet. Check that it is shared with the service account.",
      runs: [],
      config: {},
    });
  }
}
