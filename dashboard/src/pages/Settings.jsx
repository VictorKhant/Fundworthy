import { useEffect, useState } from "react";
import Organization from "../components/Organization";
import { Busy } from "../components/Spinner";
import { api } from "../api";
import { authEnabled, signOutNow } from "../auth";

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
  // Which of the three is running, not just "something is". They take visibly different
  // amounts of time — checking a key is a round trip to Anthropic — so the spinner has to
  // land on the button that is actually working.
  const [doing, setDoing] = useState(null); // "save" | "test" | "remove" | null
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const busy = doing !== null;

  async function save() {
    setDoing("save");
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
      setDoing(null);
    }
  }

  async function test() {
    setDoing("test");
    setError(null);
    setResult(null);
    try {
      setResult(await api.settings.testKey(key.trim() || undefined));
    } catch (e) {
      setError(e.message);
    } finally {
      setDoing(null);
    }
  }

  async function remove() {
    if (!window.confirm("Remove the saved key? Searches will stop being scored until you add one.")) return;
    setDoing("remove");
    try {
      await api.settings.deleteKey();
      setResult({ ok: true, message: "Removed." });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setDoing(null);
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
          <Busy className="text notice-action" busy={doing === "test"}
                busyLabel="Checking" onClick={test} disabled={busy}>
            Check it still works
          </Busy>
        </div>
      )}

      {/* A local install only. On a deployed Fundworthy the environment key does not
          resolve for anybody, so every org saves its own here — see
          `app/secrets.py: resolve_api_key`. */}
      {!state.has_api_key && state.api_key_source === "environment" && (
        <div className="notice plain">
          <strong>No key is saved here</strong> — but this is a local install, and the
          researcher is using one (<code>{state.env_key_hint}</code>) from this machine's{" "}
          <code>.env</code>, so searches will still be scored. Saving a key here takes
          priority over it, and is the one to rely on.
        </div>
      )}

      {/* This is the state that stops the app working, so it says so. It used to read
          "the researcher can still find and filter pages, but it cannot read or score
          them", which describes a degraded mode that no longer exists: without a key a
          search is refused up front rather than crawling for ten minutes to produce
          nothing. */}
      {!state.key_available && (
        <div className="notice error">
          <strong>No key yet, so searches will not run.</strong> Fundworthy reads funders'
          pages with Claude and there is nothing here to read them with. Paste a key below
          and the Search button on <strong>This week</strong> comes back on.
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
        <Busy className="primary" busy={doing === "save"} busyLabel="Saving"
              onClick={save} disabled={busy || key.trim().length < 8}>
          Save key
        </Busy>
        {/* Checking a key before trusting it is a real capability, not a duplicate of the
            link above: that one tests what is stored, this one tests what was just typed. */}
        {key.trim().length >= 8 && (
          <Busy busy={doing === "test"} busyLabel="Checking with Anthropic"
                onClick={test} disabled={busy}>
            Check it first
          </Busy>
        )}
        {state.has_api_key && (
          <Busy className="danger" busy={doing === "remove"} busyLabel="Removing"
                onClick={remove} disabled={busy}>
            Remove saved key
          </Busy>
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
        <Busy className="dark" busy={saving} busyLabel="Saving"
              onClick={save} disabled={!dirty}>
          Save
        </Busy>
      </div>

      <p className="muted small">
        Inviting teammates and switching between organizations needs accounts, which this
        version does not have — see FUTURE.md.
      </p>
    </section>
  );
}

// Closing your account, at the bottom, behind typing your own address.
//
// The confirm step is a typed email rather than an "Are you sure?" because this is not
// reversible and the two buttons of a browser confirm are three pixels apart. Typing the
// address is a few seconds that cannot be done by accident.
//
// What it does is spelled out rather than summarised, because the honest answer is
// asymmetric and people should not have to guess at the asymmetry: the findings and the
// key go, the funder list stays. That is deliberate — a funder is a name and a grants
// page, not private research, and the intent is to fold hand-added ones into the shared
// directory so the next nonprofit in that city does not start from nothing.
function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [me, setMe] = useState(null);
  const [alone, setAlone] = useState(true);

  useEffect(() => {
    api.org.read()
      .then((org) => {
        const you = (org.members || []).find((m) => m.uid === org.you);
        setMe(you?.email || "");
        setAlone((org.members || []).length <= 1);
      })
      .catch(() => setMe(""));
  }, []);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount();
      // Signing out is what actually ends the session in this browser. Without it the
      // page sits there holding a token for an account the server no longer knows,
      // 401ing on every request — which looks like a bug rather than a goodbye.
      await signOutNow();
      window.location.assign("/welcome");
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  // Nothing to delete on a local install: there are no accounts, and the data is a file
  // on this computer. Offering the button would be offering to do nothing.
  if (!authEnabled()) return null;

  return (
    <section className="panel danger-zone">
      <h2>Close your account</h2>
      {!open ? (
        <>
          <p className="settings-lede">
            Removes you from {alone ? "this organization" : "your organization"} and
            deletes your sign-in. {alone
              ? "Since you are the only person here, this organization's findings and "
                + "saved API key are deleted with it."
              : "Your colleagues keep working; nothing of theirs is touched."}
          </p>
          <button className="danger" onClick={() => setOpen(true)}>
            Close my account…
          </button>
        </>
      ) : (
        <>
          <p className="settings-lede">This cannot be undone. Here is exactly what happens:</p>
          <ul className="tut-sub">
            <li>Your sign-in is deleted and you leave this organization.</li>
            {alone ? (
              <>
                <li>
                  <strong>Deleted:</strong> this month's findings, the search history, and
                  the saved Claude API key.
                </li>
                <li>
                  <strong>Kept:</strong> the funder list. Those are names and grants pages,
                  not private research — keeping them is how the next nonprofit in your
                  city starts with something rather than nothing.
                </li>
              </>
            ) : (
              <li>
                Your colleagues keep the funders, the findings and the key. Nothing of
                theirs is deleted.
              </li>
            )}
            <li>
              Your Claude account and its billing are Anthropic's, not ours — close that
              separately if you want to.
            </li>
          </ul>

          <label className="field">
            <span>Type <strong>{me || "your email address"}</strong> to confirm</span>
            <input value={typed} autoComplete="off" placeholder={me || ""}
                   onChange={(e) => setTyped(e.target.value)} />
          </label>

          {error && <div className="notice error">{error}</div>}

          <div className="row">
            <Busy className="danger" busy={busy} busyLabel="Closing your account"
                  disabled={!me || typed.trim().toLowerCase() !== me.toLowerCase()}
                  onClick={remove}>
              Delete my account permanently
            </Busy>
            <button className="text" onClick={() => { setOpen(false); setTyped(""); }}
                    disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      )}
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

      <DeleteAccount />

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
