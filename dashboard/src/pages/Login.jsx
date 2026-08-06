import { useState } from "react";
import {
  authEnabled, authError, createAccountWithPassword, openSignup, passwordAuth,
  sendPasswordReset, signInWithGoogle, signInWithPassword,
} from "../auth";
import { Busy } from "../components/Spinner";

// Sign in, and — now that it means something — create an account.
//
// Under Google-only these were the same act. Google owns account creation, so a first
// sign-in and a hundredth were one identical call and the two buttons on the landing page
// were two labels for one thing. With the email/password provider enabled they genuinely
// diverge, so this screen has a `mode` and the landing page's two CTAs finally lead
// somewhere different.
//
// **Creating an account does not sign you in.** That is not friction for its own sake:
// `app/auth.py` refuses any token whose address is unverified, because Firebase will
// happily create an account for an address the person does not own. Signing a new account
// straight in would look like success and then 403 on the first API call, with nothing
// the user could do about it from inside the app. So sign-up ends on "check your inbox",
// which is the actual next step.
//
// Four states, and each says what to do next rather than what went wrong:
//
//     signin   email + password, Google, forgot-password
//     signup   email + password, Google, then →
//     sent     "check your inbox" — the end of sign-up, not a failure
//     reset    "we have sent a reset link, if that address has an account"

export default function Login({ onHome, notice, mode: initialMode = "signin" }) {
  const [mode, setMode] = useState(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(null);   // which button is working
  const [error, setError] = useState(null);
  const [sentTo, setSentTo] = useState(null);

  // Sign-in is switched on, but Firebase itself never came up — a wrong web API key, a
  // blocked CDN, a deleted project. Buttons would fail every time, so they do not appear;
  // what appears is the reason, which is the only thing that helps.
  const broken = authError();
  const configured = authEnabled() && !broken;
  const passwords = configured && passwordAuth();
  const creating = mode === "signup";

  function switchTo(next) {
    setMode(next);
    setError(null);
    setSentTo(null);
    // The path follows the mode so the screen can be linked and bookmarked, and so Back
    // does what it looks like it should. replaceState, not push: toggling between two
    // halves of one form is not navigation.
    window.history.replaceState({}, "", next === "signup" ? "/signup" : "/signin");
  }

  async function run(which, fn) {
    setBusy(which);
    setError(null);
    try {
      await fn();
      // No navigation on success. The auth listener in App.jsx moves us on once Firebase
      // confirms a session, so exactly one place decides whether someone is signed in.
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const submit = (e) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Both an email address and a password, please.");
      return;
    }
    run("password", async () => {
      if (creating) {
        setSentTo(await createAccountWithPassword(email, password));
        setPassword("");
      } else {
        await signInWithPassword(email, password);
      }
    });
  };

  const forgot = () => {
    if (!email.trim()) {
      setError("Type your email address first, then press this again.");
      return;
    }
    run("reset", async () => {
      await sendPasswordReset(email);
      // Deliberately the same wording whether or not an account exists — otherwise this
      // button becomes a way to find out which addresses are registered.
      setSentTo(null);
      setError(null);
      setMode("sent-reset");
    });
  };

  // --- the two terminal screens ------------------------------------------------

  if (sentTo) {
    return (
      <Shell onHome={onHome}>
        <h1 className="auth-h1">Check your inbox</h1>
        <p className="auth-sub">
          We sent a link to <strong>{sentTo}</strong>. Open it to confirm the address, then
          come back and sign in.
        </p>
        <p className="auth-switch">
          Your account exists but cannot be used until that address is confirmed — it is
          how we know it is really yours. No email after a minute or two? Check spam, then
          try signing in, which sends the link again.
        </p>
        <button className="primary auth-cta" onClick={() => { setSentTo(null); switchTo("signin"); }}>
          Go to sign in
        </button>
      </Shell>
    );
  }

  if (mode === "sent-reset") {
    return (
      <Shell onHome={onHome}>
        <h1 className="auth-h1">Check your inbox</h1>
        <p className="auth-sub">
          If <strong>{email}</strong> has an account, a password reset link is on its way.
        </p>
        <button className="primary auth-cta" onClick={() => switchTo("signin")}>
          Back to sign in
        </button>
      </Shell>
    );
  }

  // --- the form ----------------------------------------------------------------

  return (
    <Shell onHome={onHome}>
      <h1 className="auth-h1">
        {creating ? "Create your account" : openSignup() ? "Welcome" : "Welcome back"}
      </h1>
      <p className="auth-sub">
        {creating
          ? "Free — you bring your own Claude key, and your searches are billed to you and visible to nobody else."
          : "Sign in to see this week's findings."}
      </p>

      {(broken || notice || error) && (
        <div className="notice error">{broken || notice || error}</div>
      )}

      {!configured ? (
        broken ? (
          <p className="auth-switch">
            Nobody can sign in until this is fixed on the server. The message above is what
            Firebase said; step 8 of <code>docs/DEPLOY-ORACLE.md</code> is where these
            settings come from.
          </p>
        ) : (
          // Reachable at /signin even on a localhost install, so the screen can be
          // reviewed without a deployment. It says what it is rather than showing a
          // button that cannot work.
          <p className="auth-switch">
            This install has no sign-in configured — it runs on this computer and is not
            reachable from the internet, so there is nothing to sign in to. Setting it up
            is step 8 of <code>docs/DEPLOY-ORACLE.md</code>.
          </p>
        )
      ) : (
        <>
          <div className="auth-oauth">
            <Busy
              type="button"
              className="oauth-btn"
              busy={busy === "google"}
              busyLabel="Opening Google"
              onClick={() => run("google", signInWithGoogle)}
              disabled={Boolean(busy)}
            >
              <span className="oauth-mark g" aria-hidden="true">G</span>
              Continue with Google
            </Busy>
          </div>

          {/* Worth saying once. With Google there is no separate account to make and no
              inbox to go and check, so on the create-account screen it is the faster
              door — and the one that skips the verification step entirely. */}
          {creating && passwords && (
            <p className="auth-switch">
              Google is quicker — nothing to verify, nothing to remember.
            </p>
          )}

          {passwords && (
            <>
              <div className="auth-divider">
                <span />
                <span className="auth-divider-text">or with email</span>
                <span />
              </div>

              <form onSubmit={submit}>
                <label className="field">
                  <span>Email</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@yournonprofit.org"
                    autoComplete="username"
                    required
                  />
                </label>

                <label className="field">
                  <span>Password</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    // Tells a password manager to offer a new one rather than autofill an
                    // old one, and is what stops browsers warning about the form.
                    autoComplete={creating ? "new-password" : "current-password"}
                    minLength={creating ? 8 : undefined}
                    required
                  />
                </label>

                {creating ? (
                  <p className="muted small">
                    At least 8 characters. This password opens a dashboard that can spend
                    money, so do not reuse one.
                  </p>
                ) : (
                  <div className="auth-forgot">
                    <Busy
                      type="button"
                      className="text"
                      busy={busy === "reset"}
                      busyLabel="Sending the reset link"
                      onClick={forgot}
                      disabled={Boolean(busy)}
                    >
                      Forgot your password?
                    </Busy>
                  </div>
                )}

                <Busy
                  type="submit"
                  className="primary auth-cta"
                  busy={busy === "password"}
                  busyLabel={creating ? "Creating your account" : "Signing in"}
                  disabled={Boolean(busy)}
                >
                  {creating ? "Create account" : "Sign in"}
                </Busy>
              </form>
            </>
          )}

          <p className="auth-switch">
            {creating ? (
              <>
                Already have an account?{" "}
                <button type="button" className="text" onClick={() => switchTo("signin")}>
                  Sign in
                </button>
              </>
            ) : passwords ? (
              <>
                New to Fundworthy?{" "}
                <button type="button" className="text" onClick={() => switchTo("signup")}>
                  Create an account
                </button>
              </>
            ) : (
              "Signing in with Google is signing up — there is no separate account to create."
            )}
          </p>

          {openSignup() && (
            <p className="auth-switch">
              A colleague already using Fundworthy? Ask them for an invitation code — you
              can enter it once you are signed in, and you will join their organization
              instead of starting an empty one.
            </p>
          )}

          {!openSignup() && (
            <p className="auth-switch">
              This install is limited to the people it was set up for. If{" "}
              {passwords ? "Google or your password gets" : "Google gets"} you in and
              Fundworthy does not, ask whoever set it up to add your address.
            </p>
          )}
        </>
      )}
    </Shell>
  );
}

function Shell({ onHome, children }) {
  return (
    <div className="authwrap">
      <button className="brandmark authbrand" onClick={onHome}>
        Fundworthy
        <span className="brand-dot" aria-hidden="true" />
      </button>

      <div className="authcard">{children}</div>

      <p className="auth-foot">
        Your data stays on your own server. Searches run on your own AI key, with a
        spending ceiling you set.
      </p>
    </div>
  );
}
