import { useState } from "react";

// Sign in / create account. A PLACEHOLDER — there is no auth backend, nothing is sent
// anywhere, and submitting drops you into the app regardless of what you typed. See
// auth.js for what replacing it involves.
//
// Two things it does not do, on purpose:
//
//   It does not carry Google or Microsoft logos. Both companies publish branding rules
//   for sign-in buttons, and a fake button wearing a real logo misrepresents an
//   integration that does not exist. Neutral marks now; proper branded buttons when a
//   real OAuth flow is behind them.
//
//   It does not store or validate the password. The field is here so the layout is
//   settled and so nobody has to guess later where it went — the form has no action.

export default function Login({ onDone, onHome }) {
  const [mode, setMode] = useState("signin");
  const signin = mode === "signin";

  return (
    <div className="authwrap">
      <button className="brandmark authbrand" onClick={onHome}>
        Fundworthy
        <span className="brand-dot" aria-hidden="true" />
      </button>

      <form
        className="authcard"
        onSubmit={(e) => {
          e.preventDefault();
          onDone();
        }}
      >
        <h1 className="auth-h1">{signin ? "Welcome back" : "Create your account"}</h1>
        <p className="auth-sub">
          {signin
            ? "Sign in to see this week's findings."
            : "Free forever — you bring your own AI key."}
        </p>

        <div className="auth-oauth">
          <button
            type="button"
            className="oauth-btn"
            disabled
            title="Not connected yet — there is no OAuth integration behind this"
          >
            <span className="oauth-mark g" aria-hidden="true">G</span>
            Continue with Google
          </button>
          <button
            type="button"
            className="oauth-btn"
            disabled
            title="Not connected yet — there is no OAuth integration behind this"
          >
            <span className="oauth-mark grid" aria-hidden="true">
              <span /><span /><span /><span />
            </span>
            Continue with Microsoft
          </button>
        </div>

        <div className="auth-divider">
          <span />
          <span className="auth-divider-text">or with email</span>
          <span />
        </div>

        <label className="field">
          <span>Email</span>
          <input type="email" placeholder="you@yournonprofit.org" autoComplete="off" />
        </label>

        <label className="field">
          <span>Password</span>
          <input type="password" placeholder="••••••••" autoComplete="off" />
        </label>

        {signin ? (
          <div className="auth-forgot">
            <button type="button" className="text" title="Not built yet">
              Forgot your password?
            </button>
          </div>
        ) : (
          <label className="field">
            <span>Your organization</span>
            <input type="text" placeholder="e.g. Rise San Diego" />
          </label>
        )}

        <button type="submit" className="primary auth-cta">
          {signin ? "Sign in" : "Create account"}
        </button>

        <p className="auth-switch">
          {signin ? "New to Fundworthy?" : "Already have an account?"}{" "}
          <button
            type="button"
            className="text"
            onClick={() => setMode(signin ? "signup" : "signin")}
          >
            {signin ? "Create an account" : "Sign in"}
          </button>
        </p>
      </form>

      <p className="auth-foot">
        Your data stays in your account. Searches run on your own AI key, with a spending
        ceiling you set.
      </p>
    </div>
  );
}
