import { useState } from "react";
import { api, SECTOR_LABELS } from "../api";

// The partner list, editable. This used to be a hardcoded array in agent/sources.py.
//
// The case that made it worth building: one of RISE's eight partners stopped funding
// them. Removing a funder should not require someone who can edit Python — but it also
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

function Editor({ initial, sectors, onSave, onCancel }) {
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

      <label className="field inline">
        <input
          type="checkbox"
          checked={!!form.warm}
          onChange={(e) => setForm({ ...form, warm: e.target.checked })}
        />
        <span>RISE already has a relationship with them</span>
      </label>

      <label className="field">
        <span>Notes</span>
        <textarea rows={2} value={form.notes || ""} onChange={set("notes")} />
      </label>

      <div className="row end">
        <button className="ghost" onClick={onCancel}>
          Cancel
        </button>
        <button className="primary" disabled={!form.name.trim()} onClick={() => onSave(form)}>
          Save
        </button>
      </div>
    </div>
  );
}

function Row({ funder, onToggle, onEdit, onDelete }) {
  return (
    <div className={`funder-row ${funder.active ? "" : "inactive"}`}>
      <label className="funder-tick" title="Untick to stop searching them">
        <input
          type="checkbox"
          checked={funder.active}
          onChange={(e) => onToggle(funder, e.target.checked)}
        />
      </label>

      <div className="funder-main">
        <div className="funder-name">
          {funder.name}
          {funder.warm && <span className="chip warm">Partner</span>}
          {!funder.active && <span className="chip muted">Not being searched</span>}
          {!funder.url && <span className="chip muted">No page on file</span>}
        </div>
        {funder.url && (
          <a className="small" href={funder.url} target="_blank" rel="noopener noreferrer">
            {funder.url.replace(/^https?:\/\//, "").slice(0, 64)} ↗
          </a>
        )}
        {funder.notes && <div className="muted small clamp">{funder.notes}</div>}
      </div>

      <div className="funder-sector muted small">
        {SECTOR_LABELS[funder.sector] || funder.sector}
      </div>

      <div className="row">
        <button className="ghost" onClick={() => onEdit(funder)}>
          Edit
        </button>
        <button className="ghost danger" onClick={() => onDelete(funder)}>
          Remove
        </button>
      </div>
    </div>
  );
}

export default function Funders({ funders, sectors, onChange }) {
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);

  const guard = (fn) => async (...args) => {
    setError(null);
    try {
      await fn(...args);
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  };

  const toggle = guard((f, active) => api.funders.update(f.id, { active }));
  const remove = guard((f) => {
    if (
      !window.confirm(
        `Remove ${f.name} completely?\n\nIf they have just stopped funding you, untick ` +
          `"Search this one" instead — that keeps the record of the relationship.`
      )
    ) {
      return Promise.resolve();
    }
    return api.funders.remove(f.id);
  });
  const save = guard(async (form) => {
    if (editing === "new") await api.funders.create(form);
    else await api.funders.update(editing.id, form);
    setEditing(null);
  });

  const partners = funders.filter((f) => f.warm);
  const others = funders.filter((f) => !f.warm);
  const shown = showAll ? others : others.slice(0, 4);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Funders we watch</h2>
        <button className="primary" onClick={() => setEditing("new")}>
          Add a funder
        </button>
      </div>
      <p className="muted small">
        Searched in this order: your partners first, then everyone else.{" "}
        {funders.filter((f) => f.active).length} of {funders.length} are being searched.
      </p>

      {error && <div className="notice error">{error}</div>}

      {editing === "new" && (
        <Editor
          initial={BLANK}
          sectors={sectors}
          onSave={save}
          onCancel={() => setEditing(null)}
        />
      )}

      <h3 className="sub">Partners — {partners.length}</h3>
      <div className="funder-list">
        {partners.map((f) =>
          editing && editing !== "new" && editing.id === f.id ? (
            <Editor
              key={f.id}
              initial={f}
              sectors={sectors}
              onSave={save}
              onCancel={() => setEditing(null)}
            />
          ) : (
            <Row key={f.id} funder={f} onToggle={toggle} onEdit={setEditing} onDelete={remove} />
          )
        )}
      </div>

      {others.length > 0 && (
        <>
          <h3 className="sub">Everyone else — {others.length}</h3>
          <div className="funder-list">
            {shown.map((f) =>
              editing && editing !== "new" && editing.id === f.id ? (
                <Editor
                  key={f.id}
                  initial={f}
                  sectors={sectors}
                  onSave={save}
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <Row
                  key={f.id}
                  funder={f}
                  onToggle={toggle}
                  onEdit={setEditing}
                  onDelete={remove}
                />
              )
            )}
          </div>
          {others.length > 4 && (
            <button className="ghost" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show fewer" : `Show all ${others.length}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
