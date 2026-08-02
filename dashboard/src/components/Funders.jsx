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
      <label className="funder-tick" title="Untick to take them off the search">
        <input
          type="checkbox"
          checked={funder.active}
          onChange={(e) => onToggle(funder, e.target.checked)}
        />
      </label>

      <div className="funder-main">
        <div className="funder-name">
          {funder.name}
          {/* "Partner" is a label now, not a ranking signal. RISE already receives
              money from these and does not want to reapply, so a relationship is a
              reason to consider removing a funder — never a reason to rank it up. */}
          {funder.warm && <span className="chip">Existing relationship</span>}
          {!funder.active && <span className="chip muted">On the remove list</span>}
          {!funder.url && <span className="chip muted">No page on file</span>}
        </div>
        {!funder.active && funder.exclude_reason && (
          <div className="muted small">Removed because: {funder.exclude_reason}</div>
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

      <div className="row">
        <button className="text" onClick={() => onEdit(funder)}>
          Edit
        </button>
        <button className="text danger" onClick={() => onDelete(funder)}>
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

  const toggle = guard((f, active) => {
    if (active) return api.funders.update(f.id, { active: true, exclude_reason: "" });
    // Ask why. "We already get money from them" and "they stopped funding us" both
    // mean don't search, and in six months nobody will remember which this was.
    const reason = window.prompt(
      `Take ${f.name} off the search?\n\n` +
        `They will not be fetched, read, or scored — so this costs nothing every week.\n\n` +
        `Why? (optional, but it saves you guessing later)`,
      "We already receive funding from them",
    );
    if (reason === null) return Promise.resolve();
    return api.funders.update(f.id, { active: false, exclude_reason: reason });
  });
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

  // Split on what actually changes behaviour — searched vs removed — rather than on
  // "partner vs everyone else", which no longer means anything for the search order.
  const searched = funders.filter((f) => f.active);
  const removed = funders.filter((f) => !f.active);
  const shown = showAll ? searched : searched.slice(0, 8);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Funders it watches</h2>
        <button onClick={() => setEditing("new")}>+ Add</button>
      </div>
      <p className="muted small">
        {searched.length} searched weekly · {removed.length} on the remove list. Unticking
        one costs nothing every week, rather than costing a little every week — it is not
        fetched, read, or scored.
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

      <h3 className="sub">Being searched — {searched.length}</h3>
      <div className="funder-list compact">
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
            <Row key={f.id} funder={f} onToggle={toggle} onEdit={setEditing} onDelete={remove} />
          )
        )}
      </div>
      {searched.length > 8 && (
        <button className="text funder-more" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show fewer" : `Show all ${searched.length} →`}
        </button>
      )}

      <h3 className="sub">Remove list — {removed.length}</h3>
      {removed.length === 0 ? (
        <p className="muted small">
          Nobody removed yet. If you already receive funding from a funder and would not
          reapply, untick it — every week after that, the researcher skips it entirely.
        </p>
      ) : (
        <div className="funder-list compact">
          {removed.map((f) =>
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
      )}
    </section>
  );
}
