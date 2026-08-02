import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Archive from "./pages/Archive";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";

// The shell: a sidebar and three pages. No router library — three views do not justify
// a dependency RISE would have to keep updated.

const PAGES = [
  { id: "dashboard", label: "Main dashboard", icon: "◎" },
  { id: "archive", label: "Archived findings", icon: "▤" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

function Sidebar({ page, setPage, open, setOpen }) {
  return (
    <>
      <button
        className="sidebar-toggle"
        onClick={() => setOpen(!open)}
        aria-label={open ? "Hide the menu" : "Show the menu"}
        aria-expanded={open}
      >
        ☰
      </button>

      <nav className={`sidebar ${open ? "open" : ""}`} aria-label="Sections">
        <div className="sidebar-brand">RISE</div>
        {PAGES.map((p) => (
          <button
            key={p.id}
            className={`sidebar-link ${page === p.id ? "current" : ""}`}
            onClick={() => {
              setPage(p.id);
              if (window.innerWidth < 900) setOpen(false);
            }}
            aria-current={page === p.id ? "page" : undefined}
          >
            <span className="sidebar-icon" aria-hidden="true">
              {p.icon}
            </span>
            <span>{p.label}</span>
          </button>
        ))}

        <div className="sidebar-foot muted small">
          Runs on this computer.
          <br />
          Nothing is public.
        </div>
      </nav>

      {open && <div className="scrim" onClick={() => setOpen(false)} />}
    </>
  );
}

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [open, setOpen] = useState(window.innerWidth >= 900);
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setState(await api.state());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className={`shell ${open ? "with-sidebar" : ""}`}>
      <Sidebar page={page} setPage={setPage} open={open} setOpen={setOpen} />

      <main className="page">
        {error && (
          <div className="notice error">
            {error}
            <button className="ghost" onClick={refresh}>
              Try again
            </button>
          </div>
        )}

        {!state && !error && <p className="muted">Loading…</p>}

        {state && page === "dashboard" && <Dashboard state={state} onChange={refresh} />}
        {state && page === "settings" && <Settings state={state} onChange={refresh} />}
        {page === "archive" && <Archive />}

        <footer className="muted small">
          Built at the AI Trailblazers Social Impact Hack-AI-thon, San Diego, Aug 2026.
          RISE San Diego owns this work.
        </footer>
      </main>
    </div>
  );
}
