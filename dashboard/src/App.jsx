import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { authEnabled, authError, currentUser, initAuth, onUserChange, signOutNow } from "./auth";
import GettingStarted from "./components/GettingStarted";
import JoinOrg from "./components/JoinOrg";
import Sidebar from "./components/Sidebar";
import Archive from "./pages/Archive";
import Dashboard from "./pages/Dashboard";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Settings from "./pages/Settings";

// Three screens above the app shell — the marketing page, sign-in, and the app itself —
// plus three views inside it. Still no router library: this is one lookup table and a
// popstate listener, which is less code than the dependency's import statement and
// nothing anyone has to keep updated.
//
// The paths are real, so /welcome and /signin can be linked, bookmarked and demoed.
// app/main.py's SPA fallback already serves index.html for any path that is not a file,
// so no server route was needed for this.
//
// Nothing renders until initAuth() has settled. That wait is deliberate: it is the
// difference between a returning user seeing their dashboard and watching a sign-in page
// flash past on every reload. It also means the client never guesses — whether sign-in
// exists is whatever the server just said, and the server is the thing that enforces it.

const PATHS = { "/welcome": "landing", "/signin": "login" };
const PATH_FOR = { landing: "/welcome", login: "/signin", app: "/" };

// Read from auth.js rather than from React state, because initialScreen also runs from
// the popstate handler, outside a render.
const isSignedIn = () => !authEnabled() || Boolean(currentUser());

function initialScreen() {
  const known = PATHS[window.location.pathname];
  if (known) return known;
  // Anyone the app can actually serve goes straight to the dashboard: a localhost
  // install has nobody to authenticate (CLAUDE.md §6), and a deployed one where the
  // browser already holds a session has no reason to show the marketing page to someone
  // who has been using the product for a month. Signed out, the landing page is the only
  // screen that works. Either way /welcome and /signin stay reachable by URL.
  return isSignedIn() ? "app" : "landing";
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
  const [booted, setBooted] = useState(false);
  const [user, setUser] = useState(null);
  const [notice, setNotice] = useState(null);
  const [screen, setScreen] = useState("app");
  const [page, setPageState] = useState(initialPage);

  // Ask the server whether sign-in exists, and if it does, whether this browser already
  // has a session. Only then pick a screen.
  useEffect(() => {
    let live = true;
    const settle = () => {
      if (!live) return;
      setUser(currentUser());
      setNotice(authError());
      setScreen(initialScreen());
      setBooted(true);
    };
    // `.catch` as well as `.then`, because nothing renders until `booted` is true and a
    // rejected promise here would be a permanently white page. initAuth is written not
    // to throw; this is the belt to that pair of braces.
    initAuth().then(settle, settle);
    // Sign-out, an expired token, or the allow-list refusing a valid account all arrive
    // here. Losing the session drops straight back to sign-in carrying the reason —
    // leaving the dashboard on screen with every request failing would be worse.
    const stop = onUserChange((next, why) => {
      if (!live) return;
      setUser(next);
      setNotice(why || null);
      if (!next && authEnabled()) setScreen("login");
    });
    return () => {
      live = false;
      stop();
    };
  }, []);

  const setPage = useCallback((next) => {
    setPageState(next);
    // replaceState, not push: the sidebar is a view switch, not navigation, and stacking
    // history entries would make Back feel broken inside a single-page tool.
    window.history.replaceState({}, "", next === "dashboard" ? "#/" : `#/${next}`);
  }, []);
  const [open, setOpen] = useState(window.innerWidth >= 900);
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  // Set once the person says "I'm setting this up for the first time", so the join
  // prompt does not come back on every refresh of a still-empty dashboard.
  const [startedFresh, setStartedFresh] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setState(await api.state());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // Only the app screen needs data, and only once there is someone to fetch it for.
  // Fetching behind the marketing page would mean the landing page fails to render when
  // the API is down, which is the one screen that has no business depending on it — and
  // fetching before sign-in would just be a guaranteed 401.
  useEffect(() => {
    if (screen !== "app" || !booted) return;
    if (authEnabled() && !user) return;
    refresh();
  }, [screen, booted, user, refresh]);

  useEffect(() => {
    const onPop = () => setScreen(initialScreen());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Signing in successfully leaves you standing on the sign-in page, so move on. In an
  // effect rather than in the render path — pushing history while rendering is how you
  // get a component that re-renders itself forever.
  useEffect(() => {
    if (booted && user && screen === "login") {
      window.history.replaceState({}, "", PATH_FOR.app);
      setScreen("app");
    }
  }, [booted, user, screen]);

  const go = (next) => {
    window.history.pushState({}, "", PATH_FOR[next]);
    setScreen(next);
  };

  // Held back until the server has answered. A blank moment beats a wrong screen.
  if (!booted) return null;

  const signedIn = !authEnabled() || Boolean(user);

  if (screen === "landing") {
    // Where the landing page's buttons lead depends on whether there is anything to sign
    // into. On a localhost install there is not, and routing through a sign-in page that
    // cannot work would make the wordmark a one-way door out of the dashboard.
    const enter = () => go(signedIn ? "app" : "login");
    return <Landing onSignIn={enter} onCreate={enter} />;
  }

  if (screen === "login") {
    return <Login onHome={() => go("landing")} notice={notice} />;
  }

  // The app shell itself is not a place a signed-out person can be. Reaching it is not
  // an attack — every request would 401 anyway, the server is the gate — but rendering
  // a dashboard that cannot load its own data is a worse answer than the sign-in page.
  if (!signedIn) {
    return <Login onHome={() => go("landing")} notice={notice} />;
  }

  const orgName = state?.settings?.org_name;

  // A brand-new org: signed in, nothing added, nothing chosen. Only then is "are you
  // joining a colleague?" a real question — redeeming a code MOVES you into their org,
  // so offering it to someone who has already entered their programs would be offering
  // to throw that work away.
  const untouched =
    authEnabled() &&
    !startedFresh &&
    Boolean(state) &&
    (state.funders || []).length === 0 &&
    (state.programs || []).length === 0 &&
    !state.key_available;

  return (
    <div className={`shell ${open ? "with-sidebar" : ""}`}>
      <Sidebar
        page={page}
        setPage={setPage}
        open={open}
        setOpen={setOpen}
        orgName={orgName}
        user={user}
        onBrand={() => go("landing")}
        // A real sign-out: it ends the Firebase session, which drops the token, which
        // is what actually stops this browser reaching the API. The auth listener above
        // then moves the screen. Navigating to the landing page alone would have looked
        // identical and secured nothing.
        onSignOut={async () => {
          await signOutNow();
          setState(null);
          go("landing");
        }}
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

        {state && page === "dashboard" && untouched && (
          <JoinOrg
            onJoined={async () => { setStartedFresh(true); await refresh(); }}
            onSkip={() => setStartedFresh(true)}
          />
        )}

        {state && page === "dashboard" && !untouched && (
          <GettingStarted state={state} setPage={setPage} />
        )}

        {state && page === "dashboard" && <Dashboard state={state} onChange={refresh} />}
        {state && page === "settings" && <Settings state={state} onChange={refresh} />}
        {page === "archive" && <Archive />}

        <footer>
          Fundworthy — a funding-opportunity agent for nonprofits.
        </footer>
      </main>
    </div>
  );
}
