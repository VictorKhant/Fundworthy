import { useState } from "react";
import { api, SECTOR_LABELS } from "../api";
import { useConfirm } from "./Confirm";
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
  return (
    <div className={`funder-row ${funder.active ? "" : "inactive"} ${funder.blocked ? "blocked" : ""}`}>
      {selecting ? (
        <label className="funder-tick" title={`Select ${funder.name}`}>
          <input type="checkbox" checked={selected}
                 onChange={(e) => onSelect(funder, e.target.checked)} />
        </label>
      ) : (
        <label className="funder-tick"
               title={funder.blocked ? "Blocked — put it back to search it again"
                                     : "Untick to pause it"}>
          <input
            type="checkbox"
            checked={funder.active && !funder.blocked}
            disabled={funder.blocked}
            onChange={(e) => onToggle(funder, e.target.checked)}
          />
        </label>
      )}

      <div className="funder-main">
        <div className="funder-name">
          {funder.name}
          {funder.warm && <span className="chip">Existing relationship</span>}
          {funder.blocked
            ? <span className="chip warn">Blocked</span>
            : !funder.active && <span className="chip muted">Paused</span>}
          {!funder.url && <span className="chip muted">No page on file</span>}
        </div>
        {!funder.active && funder.exclude_reason && (
          <div className="muted small">Paused because: {funder.exclude_reason}</div>
        )}
        {funder.url && (
          <a className="small" href={funder.url} target="_blank" rel="noopener noreferrer">
            {funder.url.replace(/^https?:\/\//, "").slice(0, 64)} ↗
          </a>
        )}
        {funder.notes && <div className="muted small clamp">{funder.notes}</div>}
      </div>

      <div className="funder-sector muted">
        {SECTOR_LABELS[funder.sector] || funder.sector}
      </div>

      {/* Delete is not here any more. It is the only irreversible one of the three, and
          a row action next to a tick people press weekly is one they eventually press by
          accident — so it lives in "Delete several" mode and nowhere else. */}
      <div className="row">
        {!selecting && (
          <>
            <button className="text" onClick={() => onEdit(funder)}>Edit</button>
            <button className="text" onClick={() => onBlock(funder, !funder.blocked)}>
              {funder.blocked ? "Put back" : "Block"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// How many rows before it pages. Named, because "7" appearing twice in the arithmetic
// is how a page indicator and a slice drift apart.
const PER_PAGE = 7;

export default function Funders({ funders, sectors, onChange }) {
  const [dialog, ask] = useConfirm();
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState({});
  const [showBlocked, setShowBlocked] = useState(false);

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
    <section className="panel">
      {dialog}
      <div className="panel-head">
        <h2>Funders it watches</h2>
        <div className="row">
          {selecting ? (
            <>
              <Busy className="danger" busy={false} disabled={!chosen.length}
                    onClick={deleteChosen}>
                Delete {chosen.length || ""}
              </Busy>
              <button className="text" onClick={() => { setSelecting(false); setPicked({}); }}>
                Cancel
              </button>
            </>
          ) : (
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

      {/* Above the list so it filters before paging, which is the only order that makes
          sense: searching page 1 of 9 for a name that is on page 6 finds nothing. */}
      {listed.length > PER_PAGE && (
        <input
          className="funder-search"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(0); }}
          placeholder="Search your funders by name"
          aria-label="Search your funders by name"
        />
      )}

      {editing === "new" && (
        <Editor initial={BLANK} sectors={sectors} saving={saving}
                onSave={save} onCancel={() => setEditing(null)} />
      )}

      <div className="funder-list compact">
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
          <button className="text" disabled={at === 0} onClick={() => setPage(at - 1)}>
            ← Previous
          </button>
          <span className="pager-nums">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} className={`pager-num ${i === at ? "on" : ""}`}
                      aria-current={i === at ? "page" : undefined}
                      onClick={() => setPage(i)}>
                {i + 1}
              </button>
            ))}
          </span>
          <button className="text" disabled={at >= pages - 1} onClick={() => setPage(at + 1)}>
            Next →
          </button>
        </nav>
      )}

      {/* Collapsed, with the count in the header. A blacklist is a thing you check
          rarely and want to be sure is still there. */}
      {blocked.length > 0 && (
        <div className="blocklist">
          <button className="text blocklist-head" onClick={() => setShowBlocked(!showBlocked)}
                  aria-expanded={showBlocked}>
            {showBlocked ? "▾" : "▸"} Blocked — {blocked.length}
          </button>
          {showBlocked && (
            <div className="funder-list compact">
              {blocked.map((f) => (
                <Row key={f.id} funder={f} onToggle={toggle} onEdit={setEditing}
                     onBlock={block} selecting={selecting} selected={!!picked[f.id]}
                     onSelect={(x, on) => setPicked({ ...picked, [x.id]: on })} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
