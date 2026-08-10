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

  _openSignup = Boolean(config.open_signup);
  _passwordAuth = Boolean(config.password_auth);

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

// --- email and password ------------------------------------------------------
//
// Google needs no sign-up step: the account already exists and Google has already proved
// the address belongs to whoever is holding it. Passwords have neither property, which is
// why this half of the file is longer than the Google half.
//
// The server refuses any token whose address is unverified (`app/auth.py`), and it has to
// — Firebase will create an account for any address a stranger types, so an unverified
// one proves nothing. That single rule sets the shape of everything below:
//
//     create an account  →  a verification email  →  sign out  →  verify  →  sign in
//
// Signing a new account straight in would look like it worked and then fail on the first
// API call with a 403 they could do nothing about from inside the app. Better to end the
// sign-up on a screen that says "check your inbox", which is the actual next step.

function passwordProblem(e) {
  switch (e?.code) {
    case "auth/email-already-in-use":
      return "There is already an account with that address. Sign in instead, or reset " +
        "the password if you have forgotten it.";
    case "auth/invalid-email":
      return "That does not look like an email address.";
    case "auth/weak-password":
      return "Firebase wants at least 6 characters. Longer is better — this password " +
        "protects a dashboard that can spend money.";
    case "auth/operation-not-allowed":
      return "Email and password sign-in is switched off for this Firebase project. " +
        "Enable it in Firebase console → Authentication → Sign-in method.";
    case "auth/too-many-requests":
      return "Too many attempts. Firebase has paused sign-in for this address for a few " +
        "minutes.";
    case "auth/network-request-failed":
      return "Could not reach Google. Check the connection and try again.";
    // Modern Firebase returns this for a wrong password *and* an unknown address, on
    // purpose: distinguishing them tells a stranger which addresses have accounts.
    // Repeating that distinction back in our own words would undo it.
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "That email and password do not match an account.";
    default:
      return e?.message || "Could not complete that. Try again.";
  }
}

function requireFirebase() {
  if (!firebaseAuth) {
    throw new Error(initError || "Sign-in is not configured on this install.");
  }
}

// Create the account, send the verification email, and deliberately leave them signed
// out. Resolves with the address so the caller can say whose inbox to go and look in.
export async function createAccountWithPassword(email, password) {
  requireFirebase();
  const { createUserWithEmailAndPassword, sendEmailVerification, signOut } =
    await import("firebase/auth");

  try {
    const cred = await createUserWithEmailAndPassword(firebaseAuth, email.trim(), password);
    await sendEmailVerification(cred.user);
    await signOut(firebaseAuth);
    user = null;
    announce();
    return cred.user.email;
  } catch (e) {
    // Never leave a half-made session behind: if the account was created but the email
    // failed to send, being silently signed in as an unverified user is the confusing
    // state this whole flow exists to avoid.
    try {
      if (firebaseAuth.currentUser) await signOutNow();
    } catch { /* the original error is the one worth reporting */ }
    throw new Error(passwordProblem(e));
  }
}

export async function signInWithPassword(email, password) {
  requireFirebase();
  const { sendEmailVerification, signInWithEmailAndPassword } =
    await import("firebase/auth");

  let cred;
  try {
    cred = await signInWithEmailAndPassword(firebaseAuth, email.trim(), password);
  } catch (e) {
    throw new Error(passwordProblem(e));
  }

  if (!cred.user.emailVerified) {
    // The credentials were right, so this is the one moment we are allowed to send
    // another verification email — Firebase requires a signed-in user to send one, and
    // this is the only point in the flow where an unverified person legitimately is.
    // Then straight back out, because the server will refuse this token anyway.
    let resent = true;
    try {
      await sendEmailVerification(cred.user);
    } catch {
      resent = false;   // rate-limited, almost certainly; not worth failing over
    }
    await signOutNow();
    throw new Error(
      `${cred.user.email} has not been verified yet. ` +
      (resent
        ? "We have sent the link again — open it, then sign in."
        : "Open the link in the email from Fundworthy, then sign in.")
    );
  }
}

export async function sendPasswordReset(email) {
  requireFirebase();
  const { sendPasswordResetEmail } = await import("firebase/auth");
  try {
    await sendPasswordResetEmail(firebaseAuth, email.trim());
  } catch (e) {
    // Not `auth/user-not-found`: saying "no account with that address" turns this box
    // into a way to test which addresses are registered. The caller reports the same
    // thing either way.
    if (e?.code === "auth/user-not-found") return;
    throw new Error(passwordProblem(e));
  }
}

// --- chrome ------------------------------------------------------------------

const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// Whether this deployment lets any nonprofit sign up, or is a private install behind an
// allow-list. Read from the server at boot with the rest of the sign-in config — the
// client never guesses, because the server is what enforces it.
let _openSignup = false;
export const openSignup = () => _openSignup;

// Whether Firebase's email/password provider is enabled for this project. Also from the
// server, for the same reason: a password form rendered against a project that has the
// provider switched off fails with `auth/operation-not-allowed`, which looks like a bug
// in the app rather than a setting nobody turned on.
let _passwordAuth = false;
export const passwordAuth = () => _passwordAuth;

export function initials(name) {
  return (name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase() || "?";
}

// The organization currently active, from the org_name setting. A person's home
// organization is still exactly one — that is where their admin rights live — but they
// can also join a colleague's by invitation code and switch into it without leaving
// their own; see components/OrgSwitcher.jsx.
export { orgLabel };
export const orgDisplayName = (activeName) => titleCase(orgLabel(activeName));
