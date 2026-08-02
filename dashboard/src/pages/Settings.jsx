import { useState } from "react";
import { api } from "../api";

// The API key page.
//
// CLAUDE.md §2 said "Mauri never sees a terminal, a repo, a config file, or an API key."
// The last of those has changed, deliberately: §11 Q6 asks who owns the key and the
// bill, and there is no honest answer that does not involve someone at RISE holding it.
// What survives is the part that mattered — she handles it in one box, once, and never
// again.
//
// The box is write-only. Once saved, the key is encrypted on disk and no endpoint will
// return it; the page can only ever show the last four characters. That is why there is
// a "Check it works" button: she can confirm the saved key is good without anyone having
// to read it back to her.

export default function Settings({ state, onChange }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function save() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      await api.settings.saveKey(key.trim());
      setKey("");
      setResult({ ok: true, message: "Saved. It is encrypted on this computer." });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.settings.testKey(key.trim() || undefined));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm("Remove the saved key? The agent will stop scoring until you add one.")) return;
    setBusy(true);
    try {
      await api.settings.deleteKey();
      setResult({ ok: true, message: "Removed." });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header>
        <h1>Settings</h1>
        <p className="muted">Set up once. You should not need to come back here often.</p>
      </header>

      <section className="panel">
        <h2>Claude API key</h2>
        <p className="muted small">
          This is what pays for the reading and scoring. At the current volume it costs a
          couple of dollars a month, and each search stops itself before going over the
          limit you set on the main page.
        </p>

        {state.has_api_key ? (
          <div className="notice">
            A key is saved: <code>{state.api_key_hint}</code>. It is encrypted on this
            computer and this page cannot show you the rest of it — that is on purpose.
          </div>
        ) : (
          <div className="notice">
            No key saved yet. Without one the agent can still find and filter pages, but
            it cannot read or score them.
          </div>
        )}

        <label className="field">
          <span>{state.has_api_key ? "Replace it with a new key" : "Paste your key"}</span>
          <input
            type="password"
            value={key}
            autoComplete="off"
            placeholder="sk-ant-…"
            onChange={(e) => setKey(e.target.value)}
          />
          <small className="muted">
            You get one from console.anthropic.com → API keys. Whoever's account this is
            pays the bill.
          </small>
        </label>

        <div className="row">
          <button className="primary" onClick={save} disabled={busy || key.trim().length < 8}>
            {busy ? "Working…" : "Save key"}
          </button>
          <button onClick={test} disabled={busy || (!state.has_api_key && !key.trim())}>
            Check it works
          </button>
          {state.has_api_key && (
            <button className="ghost danger" onClick={remove} disabled={busy}>
              Remove saved key
            </button>
          )}
        </div>

        {result && (
          <div className={`notice ${result.ok ? "" : "error"}`}>{result.message}</div>
        )}
        {error && <div className="notice error">{error}</div>}
      </section>

      <section className="panel">
        <h2>Turning the agent off</h2>
        <p className="muted small">
          The switch is on the main page, at the bottom of "This week's search". Turn it
          off and nothing runs — no searching, no spending — until you turn it back on.
          You do not need to ask anyone.
        </p>
      </section>

      <section className="panel">
        <h2>Where your data lives</h2>
        <p className="muted small">
          Everything — your programs, your funder list, this month's findings, and the
          key — is in a single file on this computer (<code>data/rise.db</code>). Nothing
          is sent anywhere except the funder pages the agent reads and the Claude API that
          scores them. The app is not reachable from the internet.
        </p>
      </section>
    </>
  );
}
