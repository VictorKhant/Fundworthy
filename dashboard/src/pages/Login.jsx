import { useState } from "react";
import { authEnabled, authError, signInWithGoogle } from "../auth";

// Sign in. Google, and only Google.
//
// This was a placeholder with a disabled Google button, a disabled Microsoft button, and
// an email/password form that went nowhere. The Google button is now real; the other two
// are gone rather than left sitting there disabled, because a form that cannot be
// submitted is worse than no form — it reads as a broken feature instead of a decision.
//
// One provider is the whole design, not a first instalment. The org already runs on
// Google Workspace, the allow-list is a list of email addresses, and every provider
// added is another way in to a box holding an API key. Passwords in particular would
// mean owning reset flows, storage and lockouts — for a handful of named people who all
// already have a Google account.
//
// Getting in still takes two things: Google proves who you are, and the server's
// ALLOWED_EMAILS decides whether you are allowed. A valid Google account that is not on
// the list comes straight back here with the reason, which is why `notice` exists.

export default function Login({ onHome, notice }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Sign-in is switched on, but Firebase itself never came up — a wrong web API key, a
  // blocked CDN, a deleted project. The button would fail every time, so it does not
  // appear; what appears is the reason, which is the only thing that helps.
  const broken = authError();
  const configured = authEnabled() && !broken;

  async function go() {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
      // No navigation here on purpose. The auth listener in App.jsx moves us on once
      // Firebase confirms the session, so there is exactly one place that decides
      // whether someone is signed in.
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="authwrap">
      <button className="brandmark authbrand" onClick={onHome}>
        Fundworthy
        <span className="brand-dot" aria-hidden="true" />
      </button>

      <div className="authcard">
        <h1 className="auth-h1">Welcome back</h1>
        <p className="auth-sub">Sign in to see this week's findings.</p>

        {(broken || notice || error) && (
          <div className="notice error">{broken || notice || error}</div>
        )}

        {configured ? (
          <>
            <div className="auth-oauth">
              <button type="button" className="oauth-btn" onClick={go} disabled={busy}>
                <span className="oauth-mark g" aria-hidden="true">G</span>
                {busy ? "Opening Google…" : "Continue with Google"}
              </button>
            </div>
            <p className="auth-switch">
              Sign-in is limited to the people this install was set up for. If Google lets
              you in and Fundworthy does not, ask whoever set it up to add your address.
            </p>
          </>
        ) : broken ? (
          <p className="auth-switch">
            Nobody can sign in until this is fixed on the server. The message above is
            what Firebase said; step 8 of <code>docs/DEPLOY-ORACLE.md</code> is where
            these settings come from.
          </p>
        ) : (
          // Reachable at /signin even on a localhost install, so the screen can be
          // reviewed without a deployment. It says what it is rather than showing a
          // button that cannot work.
          <p className="auth-switch">
            This install has no sign-in configured — it runs on this computer and is not
            reachable from the internet, so there is nothing to sign in to. Setting up
            Google sign-in is step 8 of <code>docs/DEPLOY-ORACLE.md</code>.
          </p>
        )}
      </div>

      <p className="auth-foot">
        Your data stays on your own server. Searches run on your own AI key, with a
        spending ceiling you set.
      </p>
    </div>
  );
}
