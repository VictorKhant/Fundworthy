import { useEffect, useRef, useState } from "react";
import { api, SECTOR_LABELS } from "../api";
import { useConfirm } from "./Confirm";
import Icon, { IconButton } from "./Icon";
import { Busy } from "./Spinner";

// The partner list, editable. This used to be a hardcoded array in agent/sources.py.
//
// The case that made it worth building: one of the organization's eight partners stopped
// funding them. Removing a funder should not require someone who can edit Python — but it also
// should not erase the fact that the relationship existed. So the primary action here is
// the "Search this one" tick, not Delete: untick and the agent stops spending requests
// on them while the record stays. Delete is there, behind a confirm, for a row that was
// simply wrong.

const BLANK = {
  name: "",
  url: "",
  sector: "foundation",
  region: "",
  warm: false,
  active: true,
  notes: "",
};

function Editor({ initial, sectors, onSave, onCancel, saving }) {
  const [form, setForm] = useState({ ...BLANK, ...initial });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="card editing">
      <label className="field">
        <span>Funder name</span>
        <input value={form.name} onChange={set("name")} placeholder="San Diego Foundation" />
      </label>

      <label className="field">
        <span>Their grants page</span>
        <input
          value={form.url || ""}
          onChange={set("url")}
          placeholder="https://…"
        />
        <small className="muted">
          The page that lists what they are funding — not their homepage, if you can help it.
        </small>
      </label>

      <label className="field">
        <span>What kind of funder is this?</span>
        <select value={form.sector} onChange={set("sector")}>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {SECTOR_LABELS[s] || s}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Where do they give money?</span>
        <input
          value={form.region || ""}
          onChange={set("region")}
          placeholder="e.g. San Diego County, or leave blank if not restricted"
        />
        <small className="muted">
          Only if their own page says so — a county, a region, "statewide California".
          Shown on the row so it is not buried in notes; not a filter, so leaving it
          blank never hides this funder from anyone.
        </small>
      </label>

      {/* Yours to state, and nobody else's. The starter lists used to arrive with this
          already ticked on eight funders, because the shipped registry records the pilot
          organisation's relationships — so an account three minutes old opened this page
          and was told it had relationships it had never had. */}
      <label className="field inline">
        <input
          type="checkbox"
          checked={!!form.warm}
          onChange={(e) => setForm({ ...form, warm: e.target.checked })}
        />
        <span>We already receive funding from them</span>
      </label>

      <label className="field">
        <span>Notes</span>
        <textarea rows={2} value={form.notes || ""} onChange={set("notes")} />
      </label>

      <div className="row end">
        <button className="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <Busy className="primary" busy={saving} busyLabel="Saving"
              disabled={!form.name.trim()} onClick={() => onSave(form)}>
          Save
        </Busy>
      </div>
    </div>
  );
}

function Row({ funder, onToggle, onEdit, onBlock, selecting, selected, onSelect }) {
  const host = funder.url ? funder.url.replace(/^https?:\/\//, "").split("/")[0] : "";
  const sector = SECTOR_LABELS[funder.sector] || funder.sector;
  return (
    <div className={`funder-row ${funder.active ? "" : "inactive"} ${selected ? "picked" : ""}`}>
      {/* **A button, not a native checkbox.** This one control carries the whole
          pause/resume affordance — the thing somebody presses most often on this page —
          and a 13px system checkbox is both hard to hit and impossible to theme, so in
          dark mode the accent-coloured box was the browser's idea of the accent, not
          ours. */}
      {selecting ? (
        <button
          type="button"
          className={`funder-tick ${selected ? "on" : ""}`}
          onClick={() => onSelect(funder, !selected)}
          aria-pressed={selected}
          title={`Select ${funder.name}`}
          aria-label={`Select ${funder.name}`}
        >
          {selected && <Icon name="check" size={13} />}
        </button>
      ) : (
        <button
          type="button"
          className={`funder-tick ${funder.active ? "on" : ""}`}
          onClick={() => onToggle(funder, !funder.active)}
          aria-pressed={funder.active}
          title={funder.active ? "Searched weekly — press to pause it"
                               : "Paused — press to search it again"}
          aria-label={funder.active ? `Pause ${funder.name}` : `Search ${funder.name} again`}
        >
          <Icon name={funder.active ? "check" : "pause"} size={13} />
        </button>
      )}

      <div className="funder-main">
        <div className="funder-name">
          {funder.name}
          {funder.warm && <span className="chip">Existing relationship</span>}
          {!funder.active && <span className="chip muted">Paused</span>}
          {!funder.url && <span className="chip muted">No page on file</span>}
        </div>
        {/* The sector moves under the name rather than holding a column of its own. As a
            column it was empty space on every row at desktop width and an orphaned
            fragment at mobile. Region joins it the same way — a real, researched fact
            ("Los Angeles County", "Sonoma County") that used to live only in a
            paragraph of notes nobody reads before importing a statewide list. Shown,
            not filtered: the funder is still real and still on the list either way,
            this just says which part of California it actually serves. */}
        <div className="funder-sub muted">
          {host && (
            <a href={funder.url} target="_blank" rel="noopener noreferrer">{host} ↗</a>
          )}
          {host && sector && <span aria-hidden="true"> · </span>}
          {sector}
          {sector && funder.region && <span aria-hidden="true"> · </span>}
          {funder.region && <span title="Where this funder gives money">
            <Icon name="pin" size={11} /> {funder.region}
          </span>}
        </div>
        {!funder.active && funder.exclude_reason && (
          <div className="muted small">Paused because: {funder.exclude_reason}</div>
        )}
        {funder.notes && <div className="muted small clamp">{funder.notes}</div>}
      </div>

      {/* Delete is not here any more. It is the only irreversible one of the three, and
          a row action next to a tick people press weekly is one they eventually press by
          accident — so it lives in "Delete several" mode and nowhere else. */}
      <div className="row">
        {!selecting && (
          <>
            <IconButton name="edit" label={`Edit ${funder.name}`}
                        onClick={() => onEdit(funder)} />
            <IconButton name="block" label={`Block ${funder.name}`}
                        onClick={() => onBlock(funder, true)} />
          </>
        )}
      </div>
    </div>
  );
}

// A blocked funder has no tick, no edit and no sector worth showing, so reusing `Row`
// for one rendered four dead affordances per line. Its own shape: what it is, why, and
// the single reversal.
function BlockedRow({ funder, onBlock }) {
  return (
    <div className="blocked-row">
      <span className="blocked-icon" aria-hidden="true">
        <Icon name="block" size={13} />
      </span>
      <span className="blocked-main">
        <span className="blocked-name">{funder.name}</span>
        {funder.exclude_reason && (
          <span className="muted small">{funder.exclude_reason}</span>
        )}
      </span>
      <button className="pill" onClick={() => onBlock(funder, false)}>Put back</button>
    </div>
  );
}

// How many rows before it pages. Named, because "7" appearing twice in the arithmetic
// is how a page indicator and a slice drift apart.
const PER_PAGE = 7;

export default function Funders({ funders, sectors, addSignal = 0, onChange }) {
  const [dialog, ask] = useConfirm();
  const [editing, setEditing] = useState(null);
  const panelRef = useRef(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState({});
  const [showBlocked, setShowBlocked] = useState(false);

  // "Add one you know", pressed on the contribute strip in the section above. The editor
  // lives here, so the strip sends a signal rather than trying to own a form it cannot
  // see — and the panel scrolls itself into view, because opening a form three sections
  // below the button that opened it is indistinguishable from the button doing nothing.
  useEffect(() => {
    if (!addSignal) return;
    setEditing("new");
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [addSignal]);

  const guard = (fn) => async (...args) => {
    setError(null);
    try {
      await fn(...args);
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  };

  const toggle = guard(async (f, active) => {
    if (active) return api.funders.update(f.id, { active: true, exclude_reason: "" });
    // Ask why. "We already get money from them" and "they stopped funding us" both
    // mean don't search, and in six months nobody will remember which this was.
    const answer = await ask({
      icon: "pause",
      title: `Pause ${f.name}?`,
      points: [
        "They stay on your list, greyed out, and are not fetched, read or scored.",
        "Researched lists and other nonprofits can still suggest them — pausing is "
          + "seasonal. Use Block if you never want to see them again.",
        "One click puts them back.",
      ],
      field: {
        label: "Why? (optional, but it saves you guessing later)",
        defaultValue: "We already receive funding from them",
      },
      confirmLabel: "Pause them",
    });
    if (!answer) return undefined;
    return api.funders.update(f.id, { active: false, exclude_reason: answer.value });
  });

  const block = guard(async (f, on) => {
    if (!on) return api.funders.update(f.id, { blocked: false, active: true });
    const answer = await ask({
      icon: "block",
      tone: "clay",
      title: `Block ${f.name}?`,
      points: [
        "They are never fetched, read or scored again.",
        "They stop being offered anywhere — not by the researched lists, and not by "
          + "other nonprofits on this page.",
        "Nothing is deleted, and \u201CPut back\u201D undoes this at any time.",
      ],
      confirmLabel: "Block them",
    });
    if (!answer) return undefined;
    return api.funders.update(f.id, { blocked: true });
  });

  const save = async (form) => {
    setSaving(true);
    setError(null);
    try {
      if (editing === "new") await api.funders.create(form);
      else await api.funders.update(editing.id, form);
      setEditing(null);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const chosen = Object.keys(picked).filter((id) => picked[id]);
  const deleteChosen = guard(async () => {
    const names = funders.filter((f) => picked[f.id]).map((f) => f.name);
    const answer = await ask({
      icon: "bin",
      tone: "clay",
      title: `Delete ${names.length} funder${names.length === 1 ? "" : "s"}?`,
      body: names.slice(0, 6).join(", ") + (names.length > 6 ? `, and ${names.length - 6} more` : ""),
      points: [
        "Their rows and any notes on them are deleted. This cannot be undone.",
        "Nothing they have already found is removed from your findings.",
        "If you only want them to stop being suggested, Block is reversible.",
      ],
      confirmLabel: `Delete ${names.length}`,
    });
    if (!answer) return undefined;
    for (const id of chosen) await api.funders.remove(id);
    setPicked({});
    setSelecting(false);
    return undefined;
  });

  const blocked = funders.filter((f) => f.blocked);
  const listed = funders.filter((f) => !f.blocked);
  const needle = query.trim().toLowerCase();
  const matching = needle
    ? listed.filter((f) => `${f.name} ${f.url || ""}`.toLowerCase().includes(needle))
    : listed;

  const pages = Math.max(1, Math.ceil(matching.length / PER_PAGE));
  const at = Math.min(page, pages - 1);
  const shown = matching.slice(at * PER_PAGE, at * PER_PAGE + PER_PAGE);
  const searched = listed.filter((f) => f.active).length;

  return (
    <>
    <section className="panel" ref={panelRef}>
      {dialog}
      <div className="panel-head">
        <h2>Funders it watches</h2>
        <div className="row">
          {selecting ? null : (
            <>
              <button className="text" onClick={() => setSelecting(true)}>Delete several</button>
              <button onClick={() => setEditing("new")}>+ Add</button>
            </>
          )}
        </div>
      </div>

      <p className="muted small">
        {searched} searched weekly · {listed.length - searched} paused
        {blocked.length > 0 && ` · ${blocked.length} blocked`}. Pausing costs nothing
        every week — a paused funder is not fetched, read, or scored.
      </p>

      {error && <div className="notice error">{error}</div>}

      {/* Always here, not only past seven rows. The tick's meaning changes silently in
          selection mode, so a list that suddenly grows a search box on its eighth entry
          is one more thing that moves under somebody. */}
      <div className="funder-search">
        <Icon name="search" size={14} />
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(0); }}
          placeholder="Search a funder by name"
          aria-label="Search a funder by name"
        />
        {query && (
          <IconButton name="close" label="Clear the search"
                      onClick={() => { setQuery(""); setPage(0); }} />
        )}
      </div>

      {/* Selection mode used to announce itself by silently changing what every tick in
          the list means, and nothing else. The strip says what the ticks are for now, and
          carries the two buttons that end it. */}
      {selecting && (
        <div className="selectbar">
          <span>
            {chosen.length
              ? `${chosen.length} funder${chosen.length === 1 ? "" : "s"} chosen`
              : "Tick the ones you want gone, then press Delete them"}
          </span>
          <Busy className="danger" busy={false} disabled={!chosen.length}
                onClick={deleteChosen}>
            Delete them{chosen.length ? ` (${chosen.length})` : ""}
          </Busy>
          <button className="text" onClick={() => { setSelecting(false); setPicked({}); }}>
            Cancel
          </button>
        </div>
      )}

      {editing === "new" && (
        <Editor initial={BLANK} sectors={sectors} saving={saving}
                onSave={save} onCancel={() => setEditing(null)} />
      )}

      {/* No `compact` modifier any more. It existed for a layout where this list sat in
          a half-width column and folded the row onto two lines — with the sector on the
          left of the second line and the actions on the right. The sector now lives
          under the name, so at full width that fold left the two icons floating alone on
          a line of their own. The fold survives as a media query, where it belongs. */}
      <div className="funder-list">
        {shown.map((f) =>
          editing && editing !== "new" && editing.id === f.id ? (
            <Editor key={f.id} initial={f} sectors={sectors} saving={saving}
                    onSave={save} onCancel={() => setEditing(null)} />
          ) : (
            <Row key={f.id} funder={f} onToggle={toggle} onEdit={setEditing}
                 onBlock={block} selecting={selecting} selected={!!picked[f.id]}
                 onSelect={(x, on) => setPicked({ ...picked, [x.id]: on })} />
          )
        )}
      </div>

      {matching.length === 0 && (
        <p className="muted small">
          {needle
            ? <>Nothing on your list matches “{query}”. <button className="text"
                  onClick={() => { setQuery(""); setEditing("new"); }}>Add it by hand</button></>
            : "No funders yet. Add one, or import a researched list above."}
        </p>
      )}

      {pages > 1 && (
        <nav className="pager" aria-label="Funder list pages">
          {/* Chevrons rather than "← Previous" / "Next →". They are the two most
              repeated controls on this page, which is the R10 rule for an icon, and the
              words were wide enough to push the numbers off-centre. */}
          <IconButton name="chevron" label="Previous page" className="pager-arrow back"
                      disabled={at === 0} onClick={() => setPage(at - 1)} />
          <span className="pager-nums">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} className={`pager-num ${i === at ? "on" : ""}`}
                      aria-current={i === at ? "page" : undefined}
                      onClick={() => setPage(i)}>
                {i + 1}
              </button>
            ))}
          </span>
          <IconButton name="chevron" label="Next page" className="pager-arrow"
                      disabled={at >= pages - 1} onClick={() => setPage(at + 1)} />
        </nav>
      )}
    </section>

    {/* Its own section, and called what the user calls it. It was a text button at the
        foot of the panel above reading "▸ Blocked — 3", which is a footnote on the list
        rather than the deliberate, separate thing a blacklist is. */}
    {blocked.length > 0 && (
      <section className={`panel blacklist ${showBlocked ? "open" : ""}`}>
        <button className="blacklist-head" onClick={() => setShowBlocked(!showBlocked)}
                aria-expanded={showBlocked}>
          <span className="blacklist-caret" aria-hidden="true">
            <Icon name="chevron" size={14} />
          </span>
          <span className="blacklist-icon" aria-hidden="true">
            <Icon name="block" size={13} />
          </span>
          <h2>Blacklist</h2>
          <span className="muted small">{blocked.length}</span>
          <span className="blacklist-toggle">{showBlocked ? "Hide" : "Show"}</span>
        </button>

        {showBlocked && (
          <>
            {/* "…returns to the list above, searched again" and not "paused". §4e says
                keep the Put back semantics, and those semantics are `active: true` — so
                the sentence describes what the button does rather than the button being
                changed to match a sentence. */}
            <p className="muted small">
              Never fetched, never read, never scored — and never suggested to you again.
              Put one back and it returns to the list above, searched again.
            </p>
            <div className="blocked-list">
              {blocked.map((f) => (
                <BlockedRow key={f.id} funder={f} onBlock={block} />
              ))}
            </div>
          </>
        )}
      </section>
    )}
    </>
  );
}
