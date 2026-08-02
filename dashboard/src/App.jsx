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

// Which section of the app is open, kept in the URL hash. Three reasons it is worth the
// six lines: a refresh no longer throws you back to the dashboard, you can send someone
// a link to the page you mean, and the section is addressable — which is what lets the
// handoff guide be built from screenshots of the real thing rather than mock-ups.
const PAGES = ["dashboard", "archive", "settings"];

function initialPage() {
  const want = window.location.hash.replace(/^#\/?/, "");
  return PAGES.includes(want) ? want : "dashboard";
}

export default function App() {
  const [screen, setScreen] = useState(initialScreen);
  const [page, setPageState] = useState(initialPage);

  const setPage = useCallback((next) => {
    setPageState(next);
    // replaceState, not push: the sidebar is a view switch, not navigation, and stacking
    // history entries would make Back feel broken inside a single-page tool.
    window.history.replaceState({}, "", next === "dashboard" ? "#/" : `#/${next}`);
  }, []);
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
    // Where the landing page's buttons lead depends on whether accounts notionally
    // exist. With the flag off there is nothing to sign into, and routing through a
    // placeholder form would make the wordmark a one-way door out of the dashboard.
    const enter = () => go(AUTH_ENABLED ? "login" : "app");
    return <Landing onSignIn={enter} onCreate={enter} />;
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
        onBrand={() => go("landing")}
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
