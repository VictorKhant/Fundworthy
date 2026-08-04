import { useState } from "react";
import { api, money } from "../api";

// Program cards: the thing the user ticks to say "search for this one this week".
//
// The "Build it from a link" flow is the answer to CLAUDE.md ("the user never writes a
// prompt"). They paste the program's page from the org's website; Sonnet reads it and
// fills the card in; they edit and save. Nothing is stored until they click save, and
// a card the AI drafted stays marked as a draft until they do — so the difference
// between "the AI wrote this" and "I checked this" is visible on the card itself.

const BLANK = {
  name: "",
  summary: "",
  what_it_funds: "",
  keywords: [],
  search_queries: [],
  min_award: null,
  source_url: "",
  active: false,
};

const list = (s) =>
  s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

function Editor({ initial, onSave, onCancel, globalFloor }) {
  const [form, setForm] = useState({ ...BLANK, ...initial });
  const [url, setUrl] = useState(initial?.source_url || "");
  const [drafting, setDrafting] = useState(false);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function draft() {
    setDrafting(true);
    setError(null);
    setNote(null);
    try {
      const { draft } = await api.programs.draft(url);
      setForm({ ...form, ...draft, active: form.active });
      const missing = draft.fields_missing?.length
        ? ` It could not find: ${draft.fields_missing.join(", ")}.`
        : "";
      setNote(
        `Drafted from that page (the AI rated it ${draft.page_confidence}% useful).` +
          missing +
          " Read it over and change anything that is wrong — nothing is saved until you press Save."
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setDrafting(false);
    }
  }

  return (
    <div className="card editing">
      <label className="field">
        <span>Build it from a link</span>
        <div className="row">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-organization.org/programs/…"
          />
          <button onClick={draft} disabled={drafting || !url}>
            {drafting ? "Reading the page…" : "Read this page for me"}
          </button>
        </div>
        <small className="muted">
          Paste the program's own page. The assistant reads it and fills this card in for
          you to correct — it only uses what is on that page.
        </small>
      </label>

      {note && <div className="notice">{note}</div>}
      {error && <div className="notice error">{error}</div>}

      <label className="field">
        <span>Program name</span>
        <input value={form.name} onChange={set("name")} placeholder="Arts &amp; Cultural Equity" />
      </label>

      <label className="field">
        <span>What is this program?</span>
        <textarea rows={2} value={form.summary} onChange={set("summary")} />
      </label>

      <label className="field">
        <span>What would funding pay for?</span>
        <textarea rows={2} value={form.what_it_funds} onChange={set("what_it_funds")} />
      </label>

      <label className="field">
        <span>Words funders use for this work</span>
        <textarea
          rows={2}
          value={(form.keywords || []).join(", ")}
          onChange={(e) => setForm({ ...form, keywords: list(e.target.value) })}
          placeholder="cultural equity, creative placemaking"
        />
        <small className="muted">Separate with commas.</small>
      </label>

      <label className="field">
        <span>Searches to run for this program</span>
        <textarea
          rows={3}
          value={(form.search_queries || []).join("\n")}
          onChange={(e) => setForm({ ...form, search_queries: list(e.target.value) })}
          placeholder={"arts and social justice grant California\ncultural equity funding San Diego"}
        />
        <small className="muted">One per line.</small>
      </label>

      <label className="field">
        <span>Smallest award worth applying for — just this program</span>
        <input
          type="number"
          value={form.min_award ?? ""}
          onChange={(e) =>
            setForm({ ...form, min_award: e.target.value === "" ? null : Number(e.target.value) })
          }
          placeholder={String(globalFloor)}
        />
        <small className="muted">
          Leave blank to use your usual floor of {money(globalFloor)}.
        </small>
      </label>

      <div className="row end">
        <button className="ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          className="primary"
          disabled={!form.name.trim()}
          onClick={() => onSave({ ...form, source_url: url, reviewed_by_human: true })}
        >
          Save
        </button>
      </div>
    </div>
  );
}

// A compact row, not a card. Programs live at the bottom of the page now, in a column
// half the width they used to have — so the row carries the two facts that decide
// whether to tick it (what it is, what it costs to bother) and everything else lives one
// click away in the editor.
//
// The checkbox and the text share one <label> so the whole block is a tick target. Edit
// and Remove sit outside it: nesting a button inside a label makes clicking that button
// also toggle the checkbox.
function Row({ program, globalFloor, onToggle, onEdit, onDelete }) {
  const empty = !program.summary && program.keywords.length === 0;
  const floor = program.min_award != null ? program.min_award : globalFloor;
  const searches = program.search_queries?.length || 0;

  return (
    <div className={`progrow ${program.active ? "active" : ""}`}>
      <label className="progrow-tick">
        <input
          type="checkbox"
          checked={program.active}
          onChange={(e) => onToggle(program, e.target.checked)}
        />
        <span className="progrow-main">
          <span className="progrow-title">
            {program.name}
            {program.drafted_by_ai && !program.reviewed_by_human && (
              <span className="chip inferred" title="Drafted by the assistant and not yet checked by a person">
                AI draft — review it
              </span>
            )}
          </span>
          {/* Summary and meta are separate lines rather than one joined string. Joined,
              a long summary pushed the search count and the floor past the clamp — and
              those two are the reason to read this row at all. */}
          <span className={`progrow-sub ${empty ? "unfilled" : ""}`} title={program.summary || undefined}>
            {empty
              ? "Empty card — paste the program's web page and the assistant fills it in"
              : program.summary}
          </span>
          {!empty && (
            <span className="progrow-meta">
              {searches > 0 && `${searches} ${searches === 1 ? "search" : "searches"} · `}
              floor {money(floor)}
            </span>
          )}
        </span>
      </label>

      <span className="progrow-actions">
        <button className="text" onClick={() => onEdit(program)}>
          Edit
        </button>
        <button className="text danger" onClick={() => onDelete(program)}>
          Remove
        </button>
      </span>
    </div>
  );
}

export default function Programs({ programs, globalFloor, onChange }) {
  const [editing, setEditing] = useState(null); // program | "new" | null
  const [error, setError] = useState(null);

  const guard = (fn) => async (...args) => {
    setError(null);
    try {
      await fn(...args);
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  };

  const toggle = guard((p, active) => api.programs.update(p.id, { active }));
  const remove = guard((p) => {
    if (!window.confirm(`Remove "${p.name}"? This does not delete anything it found.`)) {
      return Promise.resolve();
    }
    return api.programs.remove(p.id);
  });
  const save = guard(async (form) => {
    if (editing === "new") await api.programs.create(form);
    else await api.programs.update(editing.id, form);
    setEditing(null);
  });

  const activeCount = programs.filter((p) => p.active).length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Your programs</h2>
        <button onClick={() => setEditing("new")}>+ Add</button>
      </div>
      <p className="muted small">
        Tick the ones to search for this week. {activeCount} of {programs.length} ticked.
        {activeCount === 0 && " Nothing is ticked, so a search would have nothing to look for."}
      </p>

      {error && <div className="notice error">{error}</div>}

      {editing === "new" && (
        <Editor
          initial={BLANK}
          globalFloor={globalFloor}
          onSave={save}
          onCancel={() => setEditing(null)}
        />
      )}

      <div className="proglist">
        {programs.map((p) =>
          editing && editing !== "new" && editing.id === p.id ? (
            <Editor
              key={p.id}
              initial={p}
              globalFloor={globalFloor}
              onSave={save}
              onCancel={() => setEditing(null)}
            />
          ) : (
            <Row
              key={p.id}
              program={p}
              globalFloor={globalFloor}
              onToggle={toggle}
              onEdit={setEditing}
              onDelete={remove}
            />
          )
        )}
      </div>
    </section>
  );
}
