// Every call the dashboard makes. One file so the API surface is readable in one go.
//
// In dev, Vite serves the page on :5173 and the API lives on :8000. In production
// start.sh serves both from :8000, so the base is empty and requests are same-origin.
const BASE = import.meta.env.DEV ? "http://localhost:8000" : "";

// Sign-in, injected rather than imported. auth.js already imports orgLabel from here, so
// importing it back would be a cycle; and this way the whole file still works untouched
// on a localhost install where there is nothing to authenticate. Both stay null until
// auth.js decides the server has sign-in switched on.
let tokenProvider = null;
let authFailureHandler = null;

export function setTokenProvider(fn) {
  tokenProvider = fn;
}

export function setAuthFailureHandler(fn) {
  authFailureHandler = fn;
}

// Every call, not once per session: Firebase ID tokens expire hourly and the provider
// refreshes them on demand. See the note in auth.js.
async function authHeaders() {
  if (!tokenProvider) return {};
  const token = await tokenProvider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function send(path, options = {}) {
  try {
    return await fetch(BASE + path, {
      ...options,
      headers: { ...(await authHeaders()), ...(options.headers || {}) },
    });
  } catch {
    // The single most likely failure for a non-technical user: they opened the page
    // but the server is not running. Say that, rather than "Failed to fetch".
    throw new Error(
      "Could not reach the app. Is it still running? Start it again with ./start.sh"
    );
  }
}

// 401 — no token, or an expired one. 403 — a real Google account the allow-list refuses.
// Both mean the dashboard cannot continue, and both are handed to auth.js so the app can
// return to the sign-in screen carrying the reason. A 403 especially must not be shown as
// a generic error: "not on the allow-list" is a thing the user can act on by asking
// someone, and "Something went wrong" is not.
async function guard(res, body) {
  const message =
    body.detail ||
    (res.status === 401 ? "Sign in to use Fundworthy." : "You are not allowed in here.");
  if (authFailureHandler) await authFailureHandler(message);
  return new Error(message);
}

async function request(path, options = {}) {
  const res = await send(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (res.status === 204) return null;

  const body = await res.json().catch(() => ({}));
  if (res.status === 401 || res.status === 403) throw await guard(res, body);
  if (!res.ok) {
    throw new Error(body.detail || body.error || `Something went wrong (${res.status}).`);
  }
  return body;
}

const get = (p) => request(p);
const post = (p, body) => request(p, { method: "POST", body: JSON.stringify(body ?? {}) });
const put = (p, body) => request(p, { method: "PUT", body: JSON.stringify(body) });
const del = (p) => request(p, { method: "DELETE" });

export const api = {
  state: () => get("/api/state"),

  settings: {
    read: () => get("/api/settings"),
    save: (changes) => put("/api/settings", changes),
    saveKey: (api_key) => post("/api/settings/api-key", { api_key }),
    deleteKey: () => del("/api/settings/api-key"),
    testKey: (api_key) => post("/api/settings/api-key/test", api_key ? { api_key } : {}),
  },

  programs: {
    list: () => get("/api/programs"),
    create: (data) => post("/api/programs", data),
    update: (id, data) => put(`/api/programs/${id}`, data),
    remove: (id) => del(`/api/programs/${id}`),
    draft: (url) => post("/api/programs/draft", { url }),
  },

  funders: {
    list: () => get("/api/funders"),
    create: (data) => post("/api/funders", data),
    update: (id, data) => put(`/api/funders/${id}`, data),
    remove: (id) => del(`/api/funders/${id}`),
  },

  opportunities: (month) => get(`/api/opportunities${month ? `?month=${month}` : ""}`),
  archive: (month) => get(`/api/archive${month ? `?month=${month}` : ""}`),

  // This used to be a plain URL on an <a download>, which was the better shape: the
  // browser's own download handling, no bytes through JS. It cannot stay that way once
  // the API needs a bearer token, because a link navigation carries cookies and nothing
  // else — there is no way to attach a header to it. So: fetch it, read the filename off
  // Content-Disposition exactly as the browser would have, and hand the blob to a
  // synthetic link. The user sees no difference; the file keeps its real name.
  downloadCsv: async (month) => {
    const res = await send(
      `/api/opportunities/export.csv${month ? `?month=${month}` : ""}`);
    if (res.status === 401 || res.status === 403) {
      throw await guard(res, await res.json().catch(() => ({})));
    }
    if (!res.ok) throw new Error(`Could not build the spreadsheet (${res.status}).`);

    const named = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = named ? named[1] : `fundworthy-${month || "current"}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  runs: {
    list: () => get("/api/runs"),
    current: () => get("/api/runs/current"),
    start: (opts) => post("/api/runs", opts),
    stop: () => post("/api/runs/stop"),
    // Which candidates a search set aside. Fetched when a stage box is opened, not with
    // the dashboard — there can be hundreds of rows and nobody reads them by default.
    rejects: (runId, { reason, limit = 60, offset = 0 } = {}) => {
      const q = new URLSearchParams({ limit, offset });
      if (reason) q.set("reason", reason);
      return get(`/api/runs/${runId}/rejects?${q}`);
    },
  },

  // Public and unauthenticated on purpose: somebody who is not signed in should still
  // learn why the page is about to blink. Uses `send` rather than `request` so a 401
  // during a restart cannot bounce a signed-in person to the sign-in screen.
  maintenance: async () => {
    try {
      const res = await send("/api/maintenance");
      return res.ok ? await res.json() : { maintenance: false };
    } catch {
      return { maintenance: false };
    }
  },

  directory: {
    read: () => get("/api/directory"),
    import: (key) => post(`/api/directory/${key}/import`),
    remove: (key) => del(`/api/directory/${key}/import`),
    shared: () => get("/api/directory/shared"),
    report: (from_org, funder_id, reason) =>
      post("/api/directory/shared/report", { from_org, funder_id, reason }),
  },

  admin: {
    reports: () => get("/api/admin/reports"),
    resolve: (id, uphold) => post(`/api/admin/reports/${id}`, { uphold }),
  },

  org: {
    read: () => get("/api/org"),
    invite: () => post("/api/org/invites"),
    revokeInvite: (code) => del(`/api/org/invites/${encodeURIComponent(code)}`),
    join: (code) => post("/api/org/join", { code }),
    removeMember: (uid) => del(`/api/org/members/${encodeURIComponent(uid)}`),
    transfer: (uid) => post("/api/org/transfer", { uid }),
  },

  // Deleting your own account. Not under `org` — it is the one action that is about the
  // person rather than the organization, and it can end the organization as a side
  // effect rather than as its purpose.
  deleteAccount: () => del("/api/account"),
};

// --- money ---------------------------------------------------------------------

// Two decimals, always. A run that cost $0.4 must not render as "$0.4" on a page whose
// whole job is to be trusted with somebody's budget.
export const usd = (n) => `$${Number(n || 0).toFixed(2)}`;

// --- formatting shared by every view -----------------------------------------

export const money = (n) =>
  n == null ? null : `$${Number(n).toLocaleString()}`;

export function awardRange(o) {
  const lo = money(o.award_min);
  const hi = money(o.award_max);
  if (lo && hi) return lo === hi ? hi : `${lo}–${hi}`;
  return hi || lo || null;
}

// Run timestamps are stored in UTC and must be READ in Pacific. This is not cosmetic
// for this product: the agent is specified to run "Wednesday 11:00 PM PT" (§9), and
// 23:00 PT is already Thursday in UTC — so rendering the stored value verbatim makes
// every on-time run look like it fired on the wrong day.
//
// The zone label comes from Intl rather than a constant, because Pacific is PDT from
// March to November; hardcoding "PST" would be an hour wrong for most of the year.
// The stored value stays UTC — only the display is converted, so the log keeps saying
// exactly what it recorded.
export function pacificStamp(value) {
  if (!value) return "never";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    timeZoneName: "short",
  }).formatToParts(d);
  const get = (t) => parts.find((p) => p.type === t)?.value ?? "";

  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")} ${get("timeZoneName")}`;
}

// Whoever this install is for. The UI used to hardcode the organization's name in a dozen
// places, which is wrong for anyone else and was never a fact the code should have been
// asserting. Blank
// reads as "your organization" rather than as a guess — the same rule the findings list
// applies to award amounts, applied to the one fact the app knows least about.
export const orgLabel = (name) => (name || "").trim() || "your organization";

export const SECTOR_LABELS = {
  warm_partner: "Partners we already work with",
  foundation: "Foundations",
  government: "Government RFPs & contracts",
  arts_agency: "Arts agencies",
  intermediary: "Networks & conveners",
  corporate: "Corporate giving",
  community: "Community funders",
  family_foundation: "Family foundations",
  community_foundation: "Community foundations",
  health_conversion: "Health foundations",
  other: "Other",
};

export const FUNDER_TYPE_LABELS = {
  private_foundation: "Private foundation",
  corporate: "Corporate",
  community: "Community foundation",
  government: "Government",
  public_agency: "Public agency",
  other: "Other",
  unknown: "Not identified",
};
