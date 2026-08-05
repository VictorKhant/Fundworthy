import { useEffect, useState } from "react";
import Organization from "../components/Organization";
import { api } from "../api";

// The API key page.
//
// CLAUDE.md said "the user never sees a terminal, a repo, a config file, or an API key."
// The last of those has changed, deliberately: §11 Q6 asks who owns the key and the bill,
// and there is no honest answer that does not involve someone at the organisation holding
// it. What survives is the part that mattered — they handle it in one box, once, and
// never again. The three-step walkthrough is the rest of that promise: "go to
// console.anthropic.com" is not instructions to someone who has never been there.
//
// The box is write-only. Once saved, the key is encrypted on disk and no endpoint will
// return it; the page can only ever show the last four characters. That is why there is a
// "Check it still works" control — they can confirm the saved key is good without anyone
// having to read it back to them.

const STEPS = [
  <>
    Go to <strong>console.anthropic.com</strong> and sign up — like creating any online
    account.
  </>,
  <>
    Open <strong>API keys</strong>, press <strong>Create key</strong>, and copy the text
    that starts with <code>sk-ant-</code>.
  </>,
  <>Paste it below and press Save. Whoever's account it is pays the bill.</>,
];

function KeyPanel({ state, onChange }) {
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
    if (!window.confirm("Remove the saved key? Searches will stop being scored until you add one.")) return;
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
    <section className="panel raised">
      <h2>Your AI key</h2>
      <p className="settings-lede">
        The key is what pays for the reading and scoring — think of it as the researcher's
        bus fare. At this volume it costs a couple of dollars a month, and every search
        stops itself at the limit you set.
      </p>

      <ol className="steps">
        {STEPS.map((s, i) => (
          <li key={i}>
            <span className="step-n" aria-hidden="true">{i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      {/* Three states, not two. "Nothing saved here" and "nothing anywhere" look identical
          on this page but behave completely differently: with a .env on the machine the
          pipeline scores regardless, and a page that only said "no key saved" would flatly
          contradict what the next run then does. */}
      {state.has_api_key && (
        <div className="notice">
          A key is saved: <code>{state.api_key_hint}</code> — encrypted, and never shown in
          full to anyone.{" "}
          <button className="text notice-action" onClick={test} disabled={busy}>
            Check it still works
          </button>
        </div>
      )}

      {!state.has_api_key && state.api_key_source === "environment" && (
        <div className="notice plain">
          <strong>No key is saved here</strong> — but the researcher is using one
          (<code>{state.env_key_hint}</code>) from a <code>.env</code> file on this
          computer, so searches will still be scored. That file is for developers. Saving a
          key here takes priority over it, and is the one to rely on.
        </div>
      )}

      {!state.key_available && (
        <div className="notice plain">
          No key saved yet. Without one the researcher can still find and filter pages, but
          it cannot read or score them.
        </div>
      )}

      <div className="keyrow">
        <label className="field">
          <span>{state.has_api_key ? "Replace it with a new key" : "Paste your key"}</span>
          <input
            type="password"
            value={key}
            autoComplete="off"
            placeholder="sk-ant-…"
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        <button className="primary" onClick={save} disabled={busy || key.trim().length < 8}>
          {busy ? "Working…" : "Save key"}
        </button>
        {/* Checking a key before trusting it is a real capability, not a duplicate of the
            link above: that one tests what is stored, this one tests what was just typed. */}
        {key.trim().length >= 8 && (
          <button onClick={test} disabled={busy}>
            Check it first
          </button>
        )}
        {state.has_api_key && (
          <button className="danger" onClick={remove} disabled={busy}>
            Remove saved key
          </button>
        )}
      </div>

      {result && <div className={`notice ${result.ok ? "" : "error"}`}>{result.message}</div>}
      {error && <div className="notice error">{error}</div>}
    </section>
  );
}

function OrgPanel({ settings, onChange }) {
  const [draft, setDraft] = useState({
    org_name: settings.org_name || "",
    org_location: settings.org_location || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDraft({ org_name: settings.org_name || "", org_location: settings.org_location || "" });
  }, [settings.org_name, settings.org_location]);

  const dirty =
    draft.org_name !== (settings.org_name || "") ||
    draft.org_location !== (settings.org_location || "");

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save(draft);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel raised">
      <h2>Organization</h2>
      <p className="settings-lede">
        Used wherever this app names you. Leave it blank and it says "your organization"
        rather than guessing.
      </p>

      <div className="knobs">
        <label className="field">
          <span>Organization name</span>
          <input
            type="text"
            value={draft.org_name}
            placeholder="Your organization"
            onChange={(e) => setDraft({ ...draft, org_name: e.target.value })}
          />
        </label>
        {/* Not a filter. It used to feed a geographic reject that ran on the words of
            every page, which was the wrong instrument — where you can apply is decided
            by which funders you chose to search, not by pattern-matching prose. This
            now only picks which city's funder directory you are shown first. */}
        <label className="field">
          <span>Your city</span>
          <input
            type="text"
            value={draft.org_location}
            placeholder="San Diego, California"
            onChange={(e) => setDraft({ ...draft, org_location: e.target.value })}
          />
          <span className="muted small">
            Only decides which funders we show you first. It never hides a grant from
            you — that is the funder list's job, and yours.
          </span>
        </label>
      </div>

      {error && <div className="notice error">{error}</div>}

      <div className="row end">
        <button className="dark" onClick={save} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      <p className="muted small">
        Inviting teammates and switching between organizations needs accounts, which this
        version does not have — see FUTURE.md.
      </p>
    </section>
  );
}

export default function Settings({ state, onChange }) {
  return (
    <>
      <header>
        <h1>Settings</h1>
        <p className="muted small">
          Set up once. You shouldn't need to come back here often.
        </p>
      </header>

      <KeyPanel state={state} onChange={onChange} />
      <OrgPanel settings={state.settings} onChange={onChange} />
      <Organization spend={state.spend} onChange={onChange} />

      <section className="panel">
        <h2>Turning it off</h2>
        <p className="settings-lede">
          The switch lives on <strong>This week</strong>, under "Adjust search settings".
          Turn it off and nothing runs and nothing is spent until you turn it back on. You
          don't need to ask anyone.
        </p>
      </section>

      <section className="panel">
        <h2>Where your data lives</h2>
        <p className="settings-lede">
          Everything — your programs, your funder list, this month's findings, and the key
          — is in a single database on the server this app runs on. Nothing is sent
          anywhere except the funder pages the researcher reads and the Claude API that
          scores them, and your searches run on your own key so they are billed to you and
          visible to nobody else.
        </p>
      </section>
    </>
  );
}
