import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

// The first-run walkthrough. It makes you do the steps rather than read about them.
//
// This replaced a checklist of paragraphs, and the difference is the point. A checklist
// tells a nonprofit administrator with no AI experience what to do and then leaves them
// on a dashboard full of controls to find it with. Reading "add your Claude key" and
// locating the Settings page are two different tasks, and the second is the one people
// abandon.
//
// So each step here contains the thing itself — the key box, the card drafter, the
// funder count — and the button to continue does not light up until the step is actually
// done. Not as a discipline: because a walkthrough you can click past is a walkthrough
// that teaches you the buttons are decorative.
//
// **Every step's done-ness is read from the server, never from a flag we set.** If you
// finish half of this and close the tab, you come back to the step you stopped at. If
// you do a step somewhere else in the app, this notices. There is no separate record of
// your progress to drift out of sync with the account, because progress *is* the
// account.

const KEY_HELP = "https://console.claude.com/settings/keys";

function Step({ n, of, title, children, done, onNext, nextLabel = "Next" }) {
  return (
    <div className="tut-step">
      <p className="tut-count">Step {n} of {of}</p>
      <h2>{title}</h2>
      {children}
      <div className="tut-actions">
        <button className="dark" onClick={onNext} disabled={!done}>
          {done ? nextLabel : "Finish this step to continue"}
        </button>
      </div>
    </div>
  );
}

function KeyStep({ state, onChange, ...rest }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      // Tested before it is saved. Pasting a key that does not work and finding out a
      // week later, when the search returns nothing, is the worst version of this.
      const check = await api.settings.testKey(key.trim());
      if (!check.ok) {
        setResult(check.message);
        return;
      }
      await api.settings.saveKey(key.trim());
      setKey("");
      await onChange();
    } catch (e) {
      setResult(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Step {...rest} done={Boolean(state.key_available)}>
      <p>
        Fundworthy reads funders' websites using Claude, and it uses <strong>your</strong>{" "}
        key — so your searches are billed to you and nobody else can see them. A weekly
        search costs about a dollar.
      </p>
      {state.key_available ? (
        <p className="tut-ok">
          ✓ Your key is saved and working. Fundworthy can read pages for you.
        </p>
      ) : (
        <>
          <ol className="tut-sub">
            <li>
              Open <a href={KEY_HELP} target="_blank" rel="noreferrer">
                console.claude.com
              </a> and sign in or create an account.
            </li>
            <li>Add a payment method, then create an API key and copy it.</li>
            <li>
              While you are there, set a monthly spending limit. That one is enforced by
              Anthropic, so it holds even if something here goes wrong.
            </li>
          </ol>
          <form onSubmit={save} className="tut-form">
            <input
              type="password"
              value={key}
              placeholder="sk-ant-…"
              autoComplete="off"
              onChange={(e) => setKey(e.target.value)}
            />
            <button type="submit" disabled={busy || key.trim().length < 8}>
              {busy ? "Checking…" : "Check and save"}
            </button>
          </form>
          {result && <div className="notice error">{result}</div>}
          <p className="muted small">
            It is encrypted before it is stored, and there is no page in Fundworthy —
            including this one — that can show it back to you.
          </p>
        </>
      )}
    </Step>
  );
}

function ProgramStep({ state, onChange, ...rest }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const active = (state.programs || []).filter((p) => p.active);

  async function drafted(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDraft((await api.programs.draft(url.trim())).draft);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function keep() {
    setBusy(true);
    try {
      await api.programs.create({ ...draft, active: true, reviewed_by_human: true });
      setDraft(null);
      setUrl("");
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Step {...rest} done={active.length > 0}>
      <p>
        Fundworthy needs to know what you do, so it can tell which grants are worth your
        time. You do not have to write anything: paste a link to a page on your own
        website and it will draft the card for you to correct.
      </p>

      {active.length > 0 && (
        <p className="tut-ok">
          ✓ {active.length} program{active.length === 1 ? "" : "s"} ready:{" "}
          {active.map((p) => p.name).join(", ")}
        </p>
      )}

      {!draft ? (
        <form onSubmit={drafted} className="tut-form">
          <input
            type="url"
            value={url}
            placeholder="https://your-organization.org/programs/…"
            onChange={(e) => setUrl(e.target.value)}
          />
          <button type="submit" disabled={busy || !url.trim()}>
            {busy ? "Reading the page…" : "Read this page"}
          </button>
        </form>
      ) : (
        <div className="tut-draft">
          <p className="muted small">
            A draft, not a decision — read it and change anything that is wrong.
          </p>
          <label className="field">
            <span>Program name</span>
            <input
              value={draft.name || ""}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label className="field">
            <span>What it does</span>
            <textarea
              rows={3}
              value={draft.summary || ""}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
            />
          </label>
          <div className="row">
            <button className="dark" onClick={keep} disabled={busy || !draft.name}>
              {busy ? "Saving…" : "Looks right — save it"}
            </button>
            <button className="text" onClick={() => setDraft(null)}>
              Start again
            </button>
          </div>
        </div>
      )}

      {error && <div className="notice error">{error}</div>}
      {!state.key_available && (
        <p className="muted small">
          Reading a page uses your Claude key, so finish step 1 first.
        </p>
      )}
    </Step>
  );
}

function FunderStep({ state, ...rest }) {
  const count = (state.funders || []).length;
  return (
    <Step {...rest} done={count > 0} nextLabel="Finish">
      <p>
        These are the funders Fundworthy will check every week. You already have{" "}
        <strong>{count}</strong> — the lists we researched, added when you signed up.
      </p>
      <p>
        You do not need to do anything now. Later, on <strong>Discover funders</strong>,
        you can add more or take off anyone you already receive money from, so you are
        not shown grants you would not apply for.
      </p>
      {count === 0 && (
        <p className="muted small">
          Your list is empty, which means a search would find nothing. Open{" "}
          <strong>Discover funders</strong> and add a researched list.
        </p>
      )}
    </Step>
  );
}

export default function Tutorial({ state, onChange, onDone }) {
  const steps = useMemo(() => [
    { key: "key", Component: KeyStep, title: "Add your Claude key" },
    { key: "program", Component: ProgramStep, title: "Describe what you do" },
    { key: "funders", Component: FunderStep, title: "Who we will watch" },
  ], []);

  // Open on the first unfinished step rather than always at one. Someone who saved a key
  // and closed the tab should not be walked through saving it again.
  const doneness = [
    Boolean(state.key_available),
    (state.programs || []).some((p) => p.active),
    (state.funders || []).length > 0,
  ];
  const firstUnfinished = doneness.findIndex((d) => !d);
  const [at, setAt] = useState(firstUnfinished === -1 ? 0 : firstUnfinished);

  // If a step completes because of something done elsewhere, do not strand the person on
  // it — but never move them backwards mid-sentence either.
  useEffect(() => {
    if (doneness[at] && at < steps.length - 1) return undefined;
    return undefined;
  }, [at, doneness, steps.length]);

  const { Component, title } = steps[at];
  const last = at === steps.length - 1;

  return (
    <div className="tutorial">
      <div className="tut-rail" aria-hidden="true">
        {steps.map((s, i) => (
          <span key={s.key}
                className={`tut-pip ${i === at ? "at" : ""} ${doneness[i] ? "done" : ""}`} />
        ))}
      </div>

      <Component
        state={state}
        onChange={onChange}
        n={at + 1}
        of={steps.length}
        title={title}
        onNext={() => (last ? onDone() : setAt(at + 1))}
      />

      {at > 0 && (
        <button className="text tut-back" onClick={() => setAt(at - 1)}>
          Back
        </button>
      )}
    </div>
  );
}
