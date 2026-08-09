import { useCallback, useEffect, useState } from "react";
import { api, SECTOR_LABELS } from "../api";
import { useConfirm } from "../components/Confirm";
import Funders from "../components/Funders";
import Icon, { IconButton } from "../components/Icon";
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
//
// **It is now last on the page.** It was sitting between the two things people actually
// came for, which is a lot of vertical space to give a control that cannot be pressed.

// One entry in either tab. Both tabs are the same shape of thing — somebody else's list
// of funders, one click to add — so they are one card, and the grid of them is what
// stops five shared funders from being taller than the funder list underneath.
function MarketCard({ icon, name, meta, body, action, extra, done }) {
  return (
    <div className={`marketcard ${done ? "done" : ""}`}>
      <div className="marketcard-head">
        <span className="marketcard-icon" aria-hidden="true">
          <Icon name={icon} size={13} />
        </span>
        <span className="marketcard-name" title={name}>{name}</span>
        {meta && <span className="marketcard-meta">{meta}</span>}
      </div>
      {body && <p className="marketcard-body">{body}</p>}
      <div className="marketcard-foot">
        {action}
        {extra}
      </div>
    </div>
  );
}

function StarterLists({ onChange }) {
  const [dialog, ask] = useConfirm();
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

  // The exact reverse of `add`, and it earns a confirm dialog the way `add` never
  // needed one: adding is undoable by removing, but removing a whole city in one
  // click, with no "are you sure", is the kind of bulk action R10's confirm-dialog
  // rule exists for. `SharedFunders.report` below is the same pattern.
  async function remove(l) {
    const answer = await ask({
      icon: "bin",
      tone: "clay",
      title: `Remove ${l.count} ${l.count === 1 ? "funder" : "funders"} from "${l.name}"?`,
      body: "Every funder this list added to yours comes off your list — including any "
            + "you have since paused, blocked, or edited.",
      points: [
        "A funder you added yourself, separately, is never touched.",
        "You can add this list again afterwards — it re-checks each funder against "
          + "your current remove list, the same as the first time.",
      ],
      confirmLabel: "Remove them",
    });
    if (!answer) return;
    setBusy(l.key);
    setError(null);
    try {
      await api.directory.remove(l.key);
      await load();
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {dialog}
      {error && <div className="notice error">{error}</div>}
      {!lists && (
        <p className="loading-line">
          <Spinner label="Loading the researched lists" />
          Loading…
        </p>
      )}

      <div className="directory">
        {(lists || []).map((l) => (
          <MarketCard
            key={l.key}
            icon="pin"
            name={l.name}
            // A funder count promises one page per row; an API adapter like Grants.gov
            // or the CA Grants Portal collapses a live search into one registry entry
            // the same way one funder's page does, and "1 funder" reads as though
            // that database holds a single grant. `is_database` says what it actually
            // is instead.
            meta={l.is_database ? "Database" : `${l.count} ${l.count === 1 ? "funder" : "funders"}`}
            body={l.description}
            done={l.imported >= l.count}
            action={l.imported >= l.count ? (
              <>
                <span className="marketcard-on">
                  <Icon name="check" size={12} /> On your list
                </span>
                <Busy className="text marketcard-remove" busy={busy === l.key}
                      busyLabel="Removing" onClick={() => remove(l)}>
                  Remove
                </Busy>
              </>
            ) : (
              <Busy className="pill primary" busy={busy === l.key} busyLabel="Adding"
                    onClick={() => add(l.key)}>
                {l.imported ? `Add the other ${l.count - l.imported}` : "Add to my list"}
              </Busy>
            )}
          />
        ))}
      </div>
    </>
  );
}

// Funders other nonprofits typed in and chose to share.
//
// Everything here is somebody else's suggestion and the page says so plainly, twice: in
// the heading and under the grid. There is no tick, no "verified" badge, no score. What
// we can honestly say is that the page opened on a particular date and mentions grants —
// that sentence comes from the server as `evidence` and is printed verbatim. Whether it
// is worth an application is a judgement nobody here can make for them, and dressing a
// reachability check up as approval is exactly the accuracy shortcut §8 forbids.
function SharedFunders({ onChange, refresh }) {
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
  useEffect(() => { load(); }, [load, refresh]);

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
      icon: "flag",
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

  return (
    <>
      {dialog}
      {error && <div className="notice error">{error}</div>}
      {!shared && (
        <p className="loading-line">
          <Spinner label="Loading suggestions" />
          Loading…
        </p>
      )}

      <div className="directory">
        {(shared || []).map((f) => (
          <MarketCard
            key={f.id}
            icon="basket"
            name={f.name}
            meta={f.added_by_count > 1
              ? `on ${f.added_by_count} lists`
              : SECTOR_LABELS[f.sector] || f.sector}
            body={`${f.evidence}${f.checked_at ? ` Checked ${f.checked_at.slice(0, 10)}.` : ""}`}
            done={Boolean(done[f.id])}
            action={done[f.id] ? (
              <span className="marketcard-on">
                <Icon name="check" size={12} />
                {done[f.id] === "added" ? "On your list" : "Reported"}
              </span>
            ) : (
              <Busy className="pill primary" busy={busy === `add:${f.id}`}
                    busyLabel="Adding" onClick={() => add(f)}>
                Add to my list
              </Busy>
            )}
            extra={!done[f.id] && (
              <IconButton name="flag" label={`Report ${f.name}`}
                          className="marketcard-report"
                          onClick={() => report(f)} />
            )}
          />
        ))}
      </div>

      {shared !== null && shared.length === 0 && (
        <p className="muted small">
          Nothing shared yet. Funders other nonprofits add by hand and choose to share
          will appear here.
        </p>
      )}

      {/* Under the grid, not above it, and still word for word. This is the §8 line: a
          reachability check is not research, and nothing on this page may imply that it
          is. Below the cards puts it against the last thing somebody reads before they
          press Add rather than the first thing they scroll past. */}
      <p className="market-caveat">
        <Icon name="warning" size={13} />
        <span>
          <strong>We have not researched these</strong> — we have only checked that the
          page opens and looks like it is about grants. Open the link before you rely on
          any of it.
        </span>
      </p>
    </>
  );
}

// Offering yours back. A checkbox that silently starts publishing rows is the one place
// on this page where a confirm genuinely earns its keep, so turning it *on* goes through
// the same three points the Settings panel spells out — what leaves, and what never
// does. Turning it off does not: stopping is not a thing anyone needs warning about.
function Contribute({ settings, onChange, onAddFunder, reload }) {
  const [dialog, ask] = useConfirm();
  const [saving, setSaving] = useState(false);
  const [mine, setMine] = useState(null);
  const on = Boolean(settings.share_funders);

  const load = useCallback(async () => {
    try {
      const all = (await api.funders.list()).funders;
      setMine(all.filter((f) => f.added_by === "user"));
    } catch {
      setMine([]);
    }
  }, []);
  useEffect(() => { load(); }, [load, settings.share_funders]);

  const offered = (mine || []).filter((f) => f.check_ok === true).length;

  async function toggle() {
    if (on) {
      setSaving(true);
      try {
        await api.settings.save({ share_funders: false });
        await onChange();
        reload?.();
      } finally {
        setSaving(false);
      }
      return;
    }
    const answer = await ask({
      icon: "upload",
      title: "Share the funders you add?",
      points: [
        "Only funders you typed in yourself. The researched lists are already available "
          + "to everyone, so re-sharing a copy of one adds nothing.",
        "Only the name, the web address, the sector and your note. Never your findings, "
          + "your programs, your spending or your name.",
        "Nothing appears until we have checked the page opens and looks like it is about "
          + "grants. Turn this off at any time and yours stop being offered.",
      ],
      confirmLabel: "Share mine",
    });
    if (!answer) return;
    setSaving(true);
    try {
      await api.settings.save({ share_funders: true });
      await onChange();
      // The checks run in a background thread, so the first look is usually too early.
      // One delayed refresh turns "nothing here" into the real answer without making
      // anybody press anything.
      setTimeout(load, 4000);
      reload?.();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`contribute ${on ? "on" : ""}`}>
      {dialog}
      <span className="contribute-icon" aria-hidden="true">
        <Icon name={on ? "check" : "upload"} size={13} />
      </span>
      <span className="contribute-text">
        <strong>{on ? "You are sharing your funders" : "Share the funders you add"}</strong>
        <span className="muted small">
          {on
            ? `${offered} of yours ${offered === 1 ? "is" : "are"} being offered to other nonprofits.`
            : "The next nonprofit in your city does not have to start from nothing."}
        </span>
      </span>
      <Busy className={on ? "pill" : "pill primary"} busy={saving}
            busyLabel="Saving" onClick={toggle}>
        {on ? "Stop sharing" : "Share mine"}
      </Busy>
      <button className="pill" onClick={onAddFunder}>Add one you know</button>
    </div>
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
// The heading is **"Add funders"** and not "Find funders": the latter collided word for
// word with the disabled "Find funders near you" card lower down, which is a completely
// different thing that does not work yet.
function Marketplace({ state, onChange, onAddFunder }) {
  const [tab, setTab] = useState("near");
  const [counts, setCounts] = useState({ near: null, shared: null });
  const [refresh, setRefresh] = useState(0);

  // The counts on the tabs. Without them, "Shared" is a tab you have to open to find out
  // whether there is anything behind it, and you have to do that every visit.
  useEffect(() => {
    api.directory.read()
      .then((d) => setCounts((c) => ({ ...c, near: (d.lists || []).length })))
      .catch(() => {});
    api.directory.shared()
      .then((d) => setCounts((c) => ({ ...c, shared: (d.funders || []).length })))
      .catch(() => {});
  }, [refresh]);

  const Count = ({ n }) =>
    n == null ? null : <span className="segmented-count">{n}</span>;

  return (
    <section className="card marketplace">
      <div className="market-head">
        <h2>
          <span className="market-icon" aria-hidden="true">
            <Icon name="basket" size={14} />
          </span>
          Add funders
        </h2>
        <div className="segmented" role="tablist" aria-label="Where to look">
          <button role="tab" aria-selected={tab === "near"}
                  onClick={() => setTab("near")}>
            <Icon name="pin" size={13} /> Near you <Count n={counts.near} />
          </button>
          <button role="tab" aria-selected={tab === "shared"}
                  onClick={() => setTab("shared")}>
            <Icon name="globe" size={13} /> Shared <Count n={counts.shared} />
          </button>
        </div>
      </div>

      <p className="muted small market-blurb">
        {tab === "near"
          ? "Funders we have already looked up and checked. Adding a list never removes "
            + "anything you have changed — a funder you paused or blocked stays that way."
          : "Funders other organizations added by hand and chose to share."}
      </p>

      {tab === "shared" && (
        <Contribute settings={state.settings} onChange={onChange}
                    onAddFunder={onAddFunder}
                    reload={() => setRefresh((n) => n + 1)} />
      )}

      {tab === "near"
        ? <StarterLists onChange={onChange} />
        : <SharedFunders onChange={onChange} refresh={refresh} />}
    </section>
  );
}

export default function Discover({ state, onChange }) {
  // A counter rather than a boolean: "Add one you know" has to be able to open the
  // editor a second time after it has been closed, and a flag that is already true does
  // not change.
  const [addFunder, setAddFunder] = useState(0);

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

      <Marketplace state={state} onChange={onChange}
                   onAddFunder={() => setAddFunder((n) => n + 1)} />
      {/* Funders renders its own list and the blacklist below it as two sibling panels,
          so "Find funders near you" — which is disabled and unbuilt — ends up last
          rather than between the two things people came here for. */}
      <Funders
        funders={state.funders}
        sectors={state.sectors_available}
        addSignal={addFunder}
        onChange={onChange}
      />
      <FindMore />
    </>
  );
}
