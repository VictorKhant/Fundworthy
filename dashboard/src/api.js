// Every call the dashboard makes. One file so the API surface is readable in one go.
//
// In dev, Vite serves the page on :5173 and the API lives on :8000. In production
// start.sh serves both from :8000, so the base is empty and requests are same-origin.
const BASE = import.meta.env.DEV ? "http://localhost:8000" : "";

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    // The single most likely failure for a non-technical user: they opened the page
    // but the server is not running. Say that, rather than "Failed to fetch".
    throw new Error(
      "Could not reach the app. Is it still running? Start it again with ./start.sh"
    );
  }

  if (res.status === 204) return null;

  const body = await res.json().catch(() => ({}));
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

  runs: {
    list: () => get("/api/runs"),
    current: () => get("/api/runs/current"),
    start: (opts) => post("/api/runs", opts),
    stop: () => post("/api/runs/stop"),
  },
};

// --- formatting shared by every view -----------------------------------------

export const money = (n) =>
  n == null ? null : `$${Number(n).toLocaleString()}`;

export function awardRange(o) {
  const lo = money(o.award_min);
  const hi = money(o.award_max);
  if (lo && hi) return lo === hi ? hi : `${lo}–${hi}`;
  return hi || lo || null;
}

export const SECTOR_LABELS = {
  warm_partner: "Partners we already work with",
  foundation: "Foundations",
  government: "Government RFPs & contracts",
  arts_agency: "Arts agencies",
  intermediary: "Networks & conveners",
  corporate: "Corporate giving",
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
