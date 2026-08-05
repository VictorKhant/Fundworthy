import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import Funders from "../components/Funders";

// Discover funders — the page for deciding who Fundworthy watches.
//
// It sits above Settings in the sidebar on purpose. Choosing funders is part of *using*
// this product, something an org returns to as it learns which ones are worth its time.
// Settings is the award floor and the API key: set once, ideally never reopened.
//
// Two halves, in the order you need them. The starter lists are what we have already
// researched — add a city, drop one you do not need. Below them sits the funder list
// itself, moved here from the weekly dashboard because "this week's findings" and "who
// we watch" are different questions, and putting both on one page meant the second
// buried the first.
//
// The third half does not exist yet: sending a stronger model out to find grantmakers in
// a city that are not in any list. Its entry point is here, disabled and saying why,
// because a button that appears the week it works is a feature nobody was waiting for —
// and because the shape of this page is the argument for building it. See FUTURE.md §4a.

function StarterLists({ onChange }) {
  const [lists, setLists] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setLists((await api.directory.read()).lists);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
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

  return (
    <section className="card">
      <h2>Researched lists</h2>
      <p className="muted">
        Funders we have already looked up and checked. Adding a list never removes
        anything you have changed — a funder you took off your list stays off.
      </p>

      {error && <div className="notice error">{error}</div>}
      {!lists && <p className="muted">Loading…</p>}

      <div className="directory">
        {(lists || []).map((l) => (
          <div key={l.key} className="directory-row">
            <div>
              <strong>{l.name}</strong>{" "}
              <span className="muted small">
                {l.count} {l.count === 1 ? "source" : "funders"}
              </span>
              <p className="muted small">{l.description}</p>
            </div>
            {l.imported >= l.count ? (
              <span className="muted small">On your list</span>
            ) : (
              <button className="secondary" onClick={() => add(l.key)}
                      disabled={busy === l.key}>
                {busy === l.key
                  ? "Adding…"
                  : l.imported
                    ? `Add the other ${l.count - l.imported}`
                    : "Add to my list"}
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function FindMore() {
  return (
    <section className="card soon">
      <h2>Find funders near you</h2>
      <p className="muted">
        Not built yet — this is what it will do, so you know what is coming.
      </p>
      <p>
        Fundworthy will search for grantmakers in a city that are not on any list yet,
        check each one is real and actually gives money, and show you what it found
        before anything joins your list. It runs on your own Claude key, like every
        other search, so you can see what it costs before you start it.
      </p>
      <p className="muted small">
        The part that takes the time is the checking. A foundation that does not exist is
        worse than one we missed — it sends you off writing an application to nobody — so
        every result has to come with the page it was found on.
      </p>
      <button className="secondary" disabled>Search a city — coming soon</button>
    </section>
  );
}

export default function Discover({ state, onChange }) {
  return (
    <>
      <header>
        <h1>Discover funders</h1>
        <p className="muted small">
          Who Fundworthy checks each week. Add the ones near you, and take off anyone you
          already receive money from — you will not be shown grants you would not apply
          for.
        </p>
      </header>

      <StarterLists onChange={onChange} />
      <FindMore />
      <Funders
        funders={state.funders}
        sectors={state.sectors_available}
        onChange={onChange}
      />
    </>
  );
}
