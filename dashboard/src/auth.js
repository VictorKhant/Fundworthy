// Sign-in. Firebase Authentication in the browser; the server verifies. (FUTURE.md §2)
//
// This file used to be a stub gated on a VITE_SHOW_AUTH build flag, and it said what
// replacing it would take: "AUTH_ENABLED stops being a build flag and becomes 'is there
// a session'". That is what happened here.
//
// Whether sign-in exists is now a fact about the *server*, read from GET /api/auth/config
// at boot, not a decision frozen into the bundle. One `npm run build` works for both a
// localhost install with no sign-in and a public deployment with it — the difference is
// four lines in the VM's .env plus a restart, which is the difference a handoff can
// survive. It also means the flag can no longer disagree with reality: the screen you get
// is the one the server will actually enforce.
//
// The Firebase SDK is loaded with a dynamic import, so an install with sign-in off never
// downloads it — Vite splits it into its own chunk.

import { orgLabel, setAuthFailureHandler, setTokenProvider } from "./api";

let config = null;      // what /api/auth/config said
let firebaseAuth = null; // the Firebase Auth instance, once signed-in is possible
let user = null;         // the Firebase user, or null
let notice = null;       // why the last sign-in ended, if it ended badly
let initError = null;    // sign-in is switched on but could not start at all
const listeners = new Set();

// --- what the app asks -------------------------------------------------------

export const authEnabled = () => config?.enabled === true;
export const currentUser = () => user;
export const authError = () => initError;

export function onUserChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function announce() {
  for (const fn of listeners) fn(user, notice);
}

// --- boot --------------------------------------------------------------------

// How long to wait for Firebase to say whether this browser is already signed in.
//
// Nothing renders until it answers (see App.jsx), so an unbounded wait is a white
// screen — which is what a corporate proxy, an ad blocker, or a Firebase outage would
// produce without this. Ten seconds is far longer than the check has ever needed; it
// exists so the failure mode is a sign-in page with an explanation rather than nothing
// at all.
const SETTLE_MS = 10_000;

// Resolves once we know whether sign-in is on AND, if it is, whether this browser is
// already signed in. Both have to be settled before the first render, or a returning
// user watches the sign-in page flash past on every reload.
//
// It resolves even when everything has gone wrong. Every path out of here leaves the app
// renderable: nothing this function can hit is worth a blank page.
export async function initAuth() {
  if (config) return config;

  try {
    const res = await fetch(`${import.meta.env.DEV ? "http://localhost:8000" : ""}/api/auth/config`);
    config = await res.json();
  } catch {
    // The server being unreachable is not a reason to show a sign-in wall — the app
    // itself reports the connection failure, in words the user can act on.
    config = { enabled: false };
  }

  if (!config.enabled) return config;

  try {
    const { initializeApp } = await import("firebase/app");
    const { browserLocalPersistence, getAuth, onAuthStateChanged, setPersistence } =
      await import("firebase/auth");

    const app = initializeApp({
      apiKey: config.api_key,
      authDomain: config.auth_domain,
      projectId: config.project_id,
    });
    firebaseAuth = getAuth(app);

    // Survive a browser restart. This is a weekly tool — anything shorter means signing
    // in every single time it is used, which is every single time.
    await setPersistence(firebaseAuth, browserLocalPersistence);

    // Every request asks for the token rather than caching one: Firebase ID tokens last
    // an hour, and `getIdToken()` refreshes silently when the current one is close to
    // expiry. Grabbing one at sign-in and reusing it would 401 the dashboard after an
    // hour open, which for a page left up during a ten-minute run is not hypothetical.
    setTokenProvider(async () => firebaseAuth.currentUser?.getIdToken() ?? null);

    // A 401 or 403 from the API lands here. 403 in particular is the allow-list refusing
    // a perfectly valid Google account, and the message says so — dropping the person
    // back to a blank sign-in page with no explanation would make it look broken instead
    // of closed.
    setAuthFailureHandler(async (message) => {
      notice = message;
      if (firebaseAuth.currentUser) await signOutNow();
      announce();
    });

    // One long-lived subscription, which also settles the first render. It has to keep
    // running afterwards: a revoked account or a sign-out in another tab arrives here,
    // and the dashboard should follow it rather than sit there looking signed in.
    await Promise.race([
      new Promise((resolve) => {
        let settled = false;
        onAuthStateChanged(
          firebaseAuth,
          (u) => {
            user = u
              ? { email: u.email, name: u.displayName || u.email, photo: u.photoURL }
              : null;
            if (user) notice = null;   // a fresh sign-in clears the last refusal
            announce();
            if (!settled) {
              settled = true;
              resolve();
            }
          },
          (e) => {
            initError = describe(e);
            resolve();
          },
        );
      }),
      new Promise((resolve) => setTimeout(resolve, SETTLE_MS)),
    ]);
  } catch (e) {
    // A bad apiKey, a blocked CDN, a project that no longer exists. Sign-in is broken
    // and nobody is getting in — but they should be told that, on a page, rather than
    // shown nothing and left to guess.
    initError = describe(e);
    firebaseAuth = null;
  }

  return config;
}

function describe(e) {
  if (e?.code === "auth/invalid-api-key" || e?.code === "auth/api-key-not-valid") {
    return "Sign-in is misconfigured: Firebase rejected this install's web API key. " +
      "Check FIREBASE_WEB_API_KEY on the server against Firebase console → Project " +
      "settings → General.";
  }
  if (e?.code === "auth/network-request-failed") {
    return "Could not reach Google to sign in. Check the connection and try again.";
  }
  return `Sign-in could not start (${e?.code || e?.message || "unknown error"}).`;
}

// --- the two buttons ---------------------------------------------------------

export async function signInWithGoogle() {
  if (!firebaseAuth) {
    throw new Error(initError || "Sign-in is not configured on this install.");
  }
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");

  const provider = new GoogleAuthProvider();
  // Always show the chooser. Shared laptops are normal in a small nonprofit office, and
  // silently reusing whichever Google account the browser saw last is how the wrong
  // person ends up looking at the org's funding pipeline.
  provider.setCustomParameters({ prompt: "select_account" });

  try {
    await signInWithPopup(firebaseAuth, provider);
  } catch (e) {
    if (e?.code === "auth/popup-closed-by-user" || e?.code === "auth/cancelled-popup-request") {
      return; // they changed their mind; not an error worth showing
    }
    if (e?.code === "auth/unauthorized-domain") {
      throw new Error(
        "This address is not on the Firebase project's authorized-domains list. " +
        "Add it in Firebase console → Authentication → Settings → Authorized domains."
      );
    }
    throw new Error(e?.message || "Could not sign in with Google.");
  }
}

export async function signOutNow() {
  if (!firebaseAuth) return;
  const { signOut } = await import("firebase/auth");
  await signOut(firebaseAuth);
  user = null;
  announce();
}

// --- chrome ------------------------------------------------------------------

const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

export function initials(name) {
  return (name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase() || "?";
}

// The organization you are signed in to, from the org_name setting. One person belongs
// to exactly one org; colleagues join yours by invitation code rather than by switching
// between several, so this returns a name to display and nothing to choose from.
export { orgLabel };
export const orgDisplayName = (activeName) => titleCase(orgLabel(activeName));
