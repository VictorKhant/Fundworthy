import { useCallback, useEffect, useState } from "react";
import { api, usd } from "../api";

// The first-run checklist for an organization that has just been created.
//
// A new org now starts genuinely empty — no funders, no program cards — because
// inheriting the pilot's 44 San Diego funders was worse than inheriting nothing. Empty is
// honest, but an empty dashboard with a Re-run button on it is not self-explanatory, so
// this says what to do in the order it has to happen.
//
// It disappears on its own once the three steps are done. Nothing to dismiss, nothing
// stored: the checklist IS the state of the account, so it cannot get out of sync with it.

function Step({ done, n, title, children }) {
  return (
    <li className={done ? "step done" : "step"}>
      <span className="step-n" aria-hidden="true">{done ? "✓" : n}</span>
      <div>
        <strong>{title}</strong>
        <p className="muted small">{children}</p>
      </div>
    </li>
  );
}

function Directory({ onChange }) {
  const [lists, setLists] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setLists((await api.directory.read()).lists); }
    catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function add(key) {
    setBusy(key);
    setError(null);
    try {
      await api.directory.import(key);
      await load();
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!lists) return null;
  return (
    <div className="directory">
      {error && <div className="notice error">{error}</div>}
      {lists.map((l) => (
        <div key={l.key} className="directory-row">
          <div>
            <strong>{l.name}</strong>{" "}
            <span className="muted small">
              {l.count} {l.count === 1 ? "source" : "funders"}
            </span>
            <p className="muted small">{l.description}</p>
          </div>
          {l.imported >= l.count ? (
            <span className="muted small">Added</span>
          ) : (
            <button className="secondary" onClick={() => add(l.key)}
                    disabled={busy === l.key}>
              {busy === l.key ? "Adding…" : l.imported ? "Add the rest" : "Add"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export default function GettingStarted({ state, setPage, onChange }) {
  const hasKey = Boolean(state.key_available);
  const hasFunders = (state.funders || []).length > 0;
  const hasProgram = (state.programs || []).some((p) => p.active);
  if (hasKey && hasFunders && hasProgram) return null;

  const cap = state.spend?.cap_usd;

  return (
    <section className="card getting-started">
      <h2>Getting started</h2>
      <p className="muted">
        Three things and Fundworthy can start looking. It takes about fifteen minutes,
        and you only do it once.
      </p>

      <ol className="steps">
        <Step done={hasKey} n="1" title="Add your Claude API key">
          Fundworthy reads funders' websites using Claude, and it uses <em>your</em> key
          so nobody else is paying for your searches — and so nobody else can see them.
          A weekly search costs about a dollar.{" "}
          {cap != null && (
            <>Your limit is set to {usd(cap)} a month and Fundworthy stops on its own
            when it gets there.</>
          )}{" "}
          When you create the key, set a spending limit on the Anthropic side too — that
          one holds even if something here goes wrong.{" "}
          <button className="text" onClick={() => setPage("settings")}>
            Open Settings
          </button>
        </Step>

        <Step done={hasProgram} n="2" title="Describe what you do">
          Add a card for each of your programs and tick the ones you want funding for.
          You do not have to write anything from scratch — paste a link to the page on
          your own website that describes the program and Fundworthy will draft the card
          for you to correct.{" "}
          <button className="text" onClick={() => setPage("dashboard")}>
            Add a program
          </button>
        </Step>

        <Step done={hasFunders} n="3" title="Choose funders to watch">
          Start from a list we have already researched, then add your own. Untick anyone
          you already receive money from, so you are not shown grants you would not
          apply for.
          <Directory onChange={onChange} />
        </Step>
      </ol>
    </section>
  );
}
