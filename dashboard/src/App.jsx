import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AUTH_ENABLED } from "./auth";
import Sidebar from "./components/Sidebar";
import Archive from "./pages/Archive";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Settings from "./pages/Settings";

// Three screens above the app shell — the marketing page, the sign-in placeholder, and
// the app itself — plus three views inside it. Still no router library: this is one
// lookup table and a popstate listener, which is less code than the dependency's import
// statement and nothing anyone has to keep updated.
//
// The paths are real, so /welcome and /signin can be linked, bookmarked and demoed.
// app/main.py's SPA fallback already serves index.html for any path that is not a file,
// so no server route was needed for this.

const PATHS = { "/welcome": "landing", "/signin": "login" };
const PATH_FOR = { landing: "/welcome", login: "/signin", app: "/" };

function initialScreen() {
  const known = PATHS[window.location.pathname];
  if (known) return known;
  // With accounts switched off this is a local, single-user, localhost-bound app, and
  // `./start.sh` must open straight onto the dashboard. The landing and sign-in screens
  // stay reachable by URL either way, so they can be reviewed without a rebuild.
  return AUTH_ENABLED ? "landing" : "app";
}

export default function App() {
  const [screen, setScreen] = useState(initialScreen);
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

  // Only the app screen needs data. Fetching it behind the marketing page would mean the
  // landing page fails to render when the API is down, which is the one screen that has
  // no business depending on it.
  useEffect(() => {
    if (screen === "app") refresh();
  }, [screen, refresh]);

  useEffect(() => {
    const onPop = () => setScreen(initialScreen());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = (next) => {
    window.history.pushState({}, "", PATH_FOR[next]);
    setScreen(next);
  };

  if (screen === "landing") {
    return <Landing onSignIn={() => go("login")} onCreate={() => go("login")} />;
  }

  if (screen === "login") {
    // Straight into the app. There is nothing to authenticate against — see auth.js.
    return <Login onDone={() => go("app")} onHome={() => go("landing")} />;
  }

  const orgName = state?.settings?.org_name;

  return (
    <div className={`shell ${open ? "with-sidebar" : ""}`}>
      <Sidebar
        page={page}
        setPage={setPage}
        open={open}
        setOpen={setOpen}
        orgName={orgName}
        onSignOut={() => go("landing")}
      />

      <main className="page">
        {error && (
          <div className="notice error">
            {error}
            <button className="text" onClick={refresh}>
              Try again
            </button>
          </div>
        )}

        {!state && !error && <p className="muted">Loading…</p>}

        {state && page === "dashboard" && <Dashboard state={state} onChange={refresh} />}
        {state && page === "settings" && <Settings state={state} onChange={refresh} />}
        {page === "archive" && <Archive />}

        <footer>
          Built at the AI Trailblazers Social Impact Hack-AI-thon, San Diego, Aug 2026.
          RISE San Diego owns this work.
        </footer>
      </main>
    </div>
  );
}
