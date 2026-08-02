import { useState } from "react";
import { api, money } from "../api";

// Program cards: the thing Mauri ticks to say "search for this one this week".
//
// The "Build it from a link" flow is the answer to CLAUDE.md §2 ("Mauri never writes a
// prompt"). She pastes the program's page from risesandiego.org; Sonnet reads it and
// fills the card in; she edits and saves. Nothing is stored until she clicks save, and
// a card the AI drafted stays marked as a draft until she does — so the difference
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
            placeholder="https://www.risesandiego.org/programs/…"
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
        <input value={form.name} onChange={set("name")} placeholder="RISE Arts" />
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

function Card({ program, globalFloor, onToggle, onEdit, onDelete }) {
  const empty = !program.summary && program.keywords.length === 0;
  return (
    <div className={`card ${program.active ? "active" : ""}`}>
      <label className="card-tick">
        <input
          type="checkbox"
          checked={program.active}
          onChange={(e) => onToggle(program, e.target.checked)}
        />
        <span className="card-title">{program.name}</span>
      </label>

      {program.summary && <p className="card-summary">{program.summary}</p>}

      {empty && (
        <p className="notice small">
          This card is empty. Press Edit and paste the program's page — the assistant will
          fill it in. Until then the agent has to guess what this program needs.
        </p>
      )}

      {program.keywords?.length > 0 && (
        <div className="tags">
          {program.keywords.slice(0, 6).map((k) => (
            <span className="chip" key={k}>
              {k}
            </span>
          ))}
        </div>
      )}

      <div className="card-meta muted small">
        {program.search_queries?.length > 0 && (
          <span>{program.search_queries.length} search(es)</span>
        )}
        <span>
          Floor {program.min_award != null ? money(program.min_award) : money(globalFloor)}
        </span>
        {program.drafted_by_ai && !program.reviewed_by_human && (
          <span className="chip inferred">
            AI draft<span className="chip-tag">unreviewed</span>
          </span>
        )}
      </div>

      <div className="row end">
        <button className="ghost" onClick={() => onEdit(program)}>
          Edit
        </button>
        <button className="ghost danger" onClick={() => onDelete(program)}>
          Remove
        </button>
      </div>
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
        <h2>Programs to find funding for</h2>
        <button className="primary" onClick={() => setEditing("new")}>
          Add a program
        </button>
      </div>
      <p className="muted small">
        Tick the programs you want searched this week. {activeCount} of {programs.length}{" "}
        ticked.
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

      <div className="cards">
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
            <Card
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
