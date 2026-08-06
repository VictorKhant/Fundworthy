import { useCallback, useEffect, useState } from "react";
import { api, SECTOR_LABELS } from "../api";
import { useConfirm } from "../components/Confirm";
import Funders from "../components/Funders";
import Spinner, { Busy } from "../components/Spinner";

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

function StarterLists({ onChange, embedded }) {
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

  const Wrap = embedded ? "div" : "section";
  return (
    <Wrap className={embedded ? "" : "card"}>
      {!embedded && <h2>Researched lists</h2>}
      <p className="muted small">
        Funders we have already looked up and checked. Adding a list never removes
        anything you have changed — a funder you paused or blocked stays that way.
      </p>

      {error && <div className="notice error">{error}</div>}
      {!lists && (
        <p className="loading-line">
          <Spinner label="Loading the researched lists" />
          Loading…
        </p>
      )}

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
              <Busy className="secondary" busy={busy === l.key} busyLabel="Adding"
                    onClick={() => add(l.key)}>
                {l.imported ? `Add the other ${l.count - l.imported}` : "Add to my list"}
              </Busy>
            )}
          </div>
        ))}
      </div>
    </Wrap>
  );
}

// Funders other nonprofits typed in and chose to share.
//
// Everything here is somebody else's suggestion and the page says so plainly, twice: in
// the heading and on every row. There is no tick, no "verified" badge, no score. What we
// can honestly say is that the page opened on a particular date and mentions grants —
// that sentence comes from the server as `evidence` and is printed verbatim. Whether it
// is worth an application is a judgement nobody here can make for them, and dressing a
// reachability check up as approval is exactly the accuracy shortcut §8 forbids.
function SharedFunders({ onChange, embedded, settings = {} }) {
  const [dialog, ask] = useConfirm();
  const [shared, setShared] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [done, setDone] = useState({});

  const load = useCallback(async () => {
    try {
      setShared((await api.directory.shared()).funders);
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function add(f) {
    setBusy(`add:${f.id}`);
    setError(null);
    try {
      await api.funders.create({
        name: f.name, url: f.url, sector: f.sector,
        funder_type: f.funder_type, notes: f.notes,
      });
      setDone({ ...done, [f.id]: "added" });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function report(f) {
    const answer = await ask({
      tone: "clay",
      title: `Report "${f.name}"?`,
      body: "Use this if the page is wrong, misleading, or not something that should be "
            + "put in front of a nonprofit.",
      points: [
        "It is hidden from everyone straight away, before anyone looks at it.",
        "Your organization is recorded, and is never shown to anyone.",
      ],
      field: { label: "What is wrong with it? (optional)" },
      confirmLabel: "Report it",
    });
    if (!answer) return;
    const reason = answer.value;
    setBusy(`report:${f.id}`);
    setError(null);
    try {
      await api.directory.report(f.from_org, f.id, reason);
      setDone({ ...done, [f.id]: "reported" });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  // Embedded, this is a tab somebody chose — so an empty one has to say it is empty
  // rather than silently rendering nothing behind a tab they just clicked.
  if (!embedded && shared !== null && shared.length === 0) return null;

  const Wrap = embedded ? "div" : "section";
  return (
    <Wrap className={embedded ? "" : "card"}>
      {dialog}
      {!embedded && <h2>Suggested by other nonprofits</h2>}
      <p className="muted small">
        Funders other organizations added by hand and chose to share. <strong>We have
        not researched these</strong> — we have only checked that the page opens and
        looks like it is about grants. Open the link before you rely on any of it.
      </p>

      {/* The contribute strip. Wired to the same `share_funders` setting the Settings
          page owns, and put here because this is the page where the value of other
          people having ticked it is visible. */}
      {embedded && (
        <label className="contribute">
          <input
            type="checkbox"
            checked={Boolean(settings.share_funders)}
            onChange={async (e) => {
              await api.settings.save({ share_funders: e.target.checked });
              await onChange();
              load();
            }}
          />
          <span>
            <strong>Share the funders I add.</strong> Only ones you typed in yourself, and
            only the name, address, sector and your note — never your findings, your
            programs or your spending.
          </span>
        </label>
      )}

      {error && <div className="notice error">{error}</div>}
      {!shared && (
        <p className="loading-line">
          <Spinner label="Loading suggestions" />
          Loading…
        </p>
      )}

      <div className="directory">
        {(shared || []).map((f) => (
          <div key={f.id} className="directory-row">
            <div>
              <strong>{f.name}</strong>{" "}
              <span className="muted small">{SECTOR_LABELS[f.sector] || f.sector}</span>
              {f.added_by_count > 1 && (
                <span className="chip">on {f.added_by_count} lists</span>
              )}
              {f.url && (
                <p className="small">
                  <a href={f.url} target="_blank" rel="noopener noreferrer">
                    {f.url.replace(/^https?:\/\//, "").slice(0, 60)} ↗
                  </a>
                </p>
              )}
              <p className="muted small">
                {f.evidence}
                {f.checked_at && ` Checked ${f.checked_at.slice(0, 10)}.`}
              </p>
            </div>
            <span className="row">
              {done[f.id] ? (
                <span className="muted small">
                  {done[f.id] === "added" ? "On your list" : "Reported"}
                </span>
              ) : (
                <>
                  <Busy className="secondary" busy={busy === `add:${f.id}`}
                        busyLabel="Adding" onClick={() => add(f)}>
                    Add to my list
                  </Busy>
                  <Busy className="text danger" busy={busy === `report:${f.id}`}
                        busyLabel="Reporting" onClick={() => report(f)}>
                    Report
                  </Busy>
                </>
              )}
            </span>
          </div>
        ))}
      </div>

      {embedded && shared !== null && shared.length === 0 && (
        <p className="muted small">
          Nothing shared yet. Funders other nonprofits add by hand and choose to share
          will appear here.
        </p>
      )}
    </Wrap>
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

// The two ways to find a funder you do not have yet, as one section with a tab — first
// on the page, because "who should I be watching?" comes before "here is who I watch".
//
// They were two stacked cards of full-width rows, which put the shared suggestions below
// the fold on any list longer than a few. Both are the same shape of thing (somebody
// else's list of funders, one click to add), so they are the same control.
function Marketplace({ state, onChange }) {
  const [tab, setTab] = useState("near");

  return (
    <section className="card marketplace">
      <div className="market-head">
        <h2>Find funders</h2>
        <div className="segmented" role="tablist" aria-label="Where to look">
          <button role="tab" aria-selected={tab === "near"}
                  onClick={() => setTab("near")}>Near you</button>
          <button role="tab" aria-selected={tab === "shared"}
                  onClick={() => setTab("shared")}>Shared</button>
        </div>
      </div>

      {tab === "near"
        ? <StarterLists onChange={onChange} embedded />
        : <SharedFunders onChange={onChange} embedded settings={state.settings} />}
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

      <Marketplace state={state} onChange={onChange} />
      <FindMore />
      <Funders
        funders={state.funders}
        sectors={state.sectors_available}
        onChange={onChange}
      />
    </>
  );
}
