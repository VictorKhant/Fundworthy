import { useCallback, useEffect, useState } from "react";
import Organization from "../components/Organization";
import Spinner, { Busy } from "../components/Spinner";
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

// Opting in to sharing the funders you added by hand.
//
// Off by default and asked for plainly. A funder list is not private — a name, a grants
// page and a sector — but "not private" is not the same as "ours to publish on their
// behalf", and an org that has never been asked has not agreed to anything.
//
// The copy is specific about what does and does not leave, because "share my funders"
// could reasonably be heard as "share my findings", which would be a very different and
// much worse thing.
function ShareFunders({ settings, onChange }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const on = Boolean(settings.share_funders);

  async function toggle(next) {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save({ share_funders: next });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel">
      <h2>Helping other nonprofits</h2>
      <p className="settings-lede">
        Funders you add by hand are research somebody did. Sharing them puts the name and
        the grants page on other nonprofits' <strong>Discover funders</strong> page, so
        the next organization in your city does not start from nothing.
      </p>

      <label className="check">
        <input type="checkbox" checked={on} disabled={saving}
               onChange={(e) => toggle(e.target.checked)} />
        Share the funders I add with other nonprofits
      </label>

      <ul className="tut-sub">
        <li>
          Only funders <strong>you typed in</strong>. The researched lists are already
          available to everyone, so re-sharing a copy of one adds nothing.
        </li>
        <li>
          Only the name, the web address, the sector and your note.{" "}
          <strong>Never your findings, your programs, your spending or your name.</strong>
        </li>
        <li>
          Nothing appears until we have checked the page opens and looks like it is about
          grants. Untick this at any time and yours stop being offered.
        </li>
      </ul>

      {saving && <p className="loading-line"><Spinner label="Saving" />Saving…</p>}
      {error && <div className="notice error">{error}</div>}
    </section>
  );
}

// The moderation queue. Only rendered for whoever `FUNDWORTHY_ADMIN_EMAILS` names, and
// the server checks again — this component simply is not fetched otherwise.
//
// A report hides the funder from everybody the moment it is filed, before anyone looks.
// So the two buttons here are "it really was bad" and "put it back", and the second one
// matters: without it a single objection would permanently remove a good funder, and
// one person's mistake would be indistinguishable from moderation.
function ReportQueue() {
  const [reports, setReports] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setReports((await api.admin.reports()).reports);
    } catch {
      setReports([]);          // not an admin, or the route is not there: show nothing
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function resolve(id, uphold) {
    setBusy(id);
    setError(null);
    try {
      await api.admin.resolve(id, uphold);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!reports || reports.length === 0) return null;

  return (
    <section className="panel danger-zone">
      <h2>Reported funders — {reports.length}</h2>
      <p className="settings-lede">
        Each of these is hidden from everyone until you decide. Open the page before you
        do; the person who reported it is not shown, and neither is the org that added it.
      </p>
      {error && <div className="notice error">{error}</div>}
      <ul className="plain">
        {reports.map((r) => (
          <li key={r.id} className="member">
            <span>
              <strong>{r.name || "(funder since deleted)"}</strong>
              {r.url && (
                <>
                  {" "}
                  <a href={r.url} target="_blank" rel="noopener noreferrer">open ↗</a>
                </>
              )}
              {r.reason && <span className="muted small"> — “{r.reason}”</span>}
            </span>
            <span className="row">
              <Busy className="text danger" busy={busy === r.id} busyLabel="Removing"
                    onClick={() => resolve(r.id, true)}>
                Take it down
              </Busy>
              <Busy className="text" busy={busy === r.id} busyLabel="Restoring"
                    onClick={() => resolve(r.id, false)}>
                It is fine — put it back
              </Busy>
            </span>
          </li>
        ))}
      </ul>
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

      <ShareFunders settings={state.settings} onChange={onChange} />
      <ReportQueue />
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
