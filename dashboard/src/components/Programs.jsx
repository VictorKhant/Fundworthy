import { useState } from "react";
import { api, money } from "../api";
import { useConfirm } from "./Confirm";
import Icon from "./Icon";
import Spinner, { Busy } from "./Spinner";

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

function Editor({ initial, onSave, onCancel, onDelete, globalFloor, saving }) {
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
          <Busy busy={drafting} busyLabel="Reading the page" onClick={draft}
                disabled={!url}>
            Read this page for me
          </Busy>
        </div>
        <small className="muted">
          Paste the program's own page. The assistant reads it and fills this card in for
          you to correct — it only uses what is on that page.
        </small>
      </label>

      {/* A spinning button is enough to say "something is happening"; this says how long
          for. Reading a page is one Sonnet call against a website we do not control, so
          it is measured in seconds, not milliseconds, and a silent five seconds is where
          people press the button again. */}
      {drafting && (
        <p className="loading-line">
          <Spinner label="Reading the page" />
          Fetching that page and reading it. Usually five to fifteen seconds.
        </p>
      )}

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

      {/* Removing lives here, bottom-left, rather than on the chip. It is rare and
          permanent, and a delete control sitting next to a tick you press every week is
          a delete control somebody eventually presses by accident. */}
      <div className="row end editor-foot">
        {onDelete && (
          <button className="text danger editor-remove" onClick={onDelete} disabled={saving}>
            Remove this program
          </button>
        )}
        <button className="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <Busy
          className="primary"
          busy={saving}
          busyLabel="Saving"
          disabled={!form.name.trim()}
          onClick={() => onSave({ ...form, source_url: url, reviewed_by_human: true })}
        >
          Save
        </Busy>
      </div>
    </div>
  );
}

// One program, as a chip. This is the top of This week now, not the bottom of it —
// "which of our programs am I searching for this week?" is a question you answer before
// reading the results, and a full-width list of rows at the foot of the page was
// answering it after.
//
// **Two buttons, never a button inside a label.** The tick and the pencil are siblings
// separated by a hairline. Nesting the pencil inside the label made clicking it toggle
// the checkbox as well — you pressed Edit and silently changed what next week searches
// for. The old row carried a comment about that; this shape makes it impossible rather
// than remembered.
//
// An **empty card cannot be ticked**, and the chip says so instead of failing when you
// try: dashed border, a clay tag, and the tick button opens the editor. The same rule is
// enforced in `repo.update_program`, because this is an affordance and that is the rule.
//
// The modifier is `unfilled`, not `empty`, and that is not a style preference: `.empty`
// is the page-level no-results block (40px padding, 14px radius). Composing the two
// turns every undescribed program into a large squared-off box in the middle of a row of
// pills. The row this replaced carried a comment saying exactly that, and this walked
// into it anyway — hence the note here as well as there.
function Chip({ program, globalFloor, onToggle, onEdit }) {
  const empty = !program.summary && program.keywords.length === 0;
  const unreviewed = program.drafted_by_ai && !program.reviewed_by_human;
  const floor = program.min_award != null ? program.min_award : globalFloor;
  const searches = program.search_queries?.length || 0;

  const detail = empty
    ? "This card has no description yet, so there is nothing to match grants against. "
      + "Click to fill it in."
    : [program.summary,
       searches > 0 ? `${searches} ${searches === 1 ? "search" : "searches"}` : null,
       `floor ${money(floor)}`].filter(Boolean).join(" · ");

  return (
    <div className={`progchip ${program.active ? "on" : ""} ${empty ? "unfilled" : ""}`}>
      <button
        type="button"
        className="progchip-tick"
        // Ticking an empty card is refused by the server, so offering the tick and then
        // showing an error would be a worse way of saying the same thing. Open the
        // editor: filling it in is the only route to ticking it anyway.
        onClick={() => (empty ? onEdit(program) : onToggle(program, !program.active))}
        aria-pressed={empty ? undefined : program.active}
        title={detail}
      >
        {/* A filled square with a stroke glyph, not a text character. The three states
            have to be distinguishable at a glance across a wrapped row of chips, and a
            bare "✓" / "+" / nothing gave the third state no mark at all — an unticked
            card and a ticked one differed by one thin character. */}
        <span className="progchip-mark" aria-hidden="true">
          <Icon name={empty ? "close" : program.active ? "check" : "add"} size={11} />
        </span>
        <span className="progchip-name">{program.name}</span>
        {empty && <span className="progchip-tag">needs filling in</span>}
        {unreviewed && (
          // Same §6 rule as .chip.inferred: a value the assistant produced and no human
          // has confirmed must not look like one a person wrote.
          <span className="chip inferred progchip-tag"
                title="Drafted by the assistant and not yet checked by a person">
            AI draft
          </span>
        )}
      </button>

      <button
        type="button"
        className="progchip-edit"
        onClick={() => onEdit(program)}
        title={`Edit ${program.name}`}
        aria-label={`Edit ${program.name}`}
      >
        <Icon name="edit" size={14} />
      </button>
    </div>
  );
}


export default function Programs({ programs, globalFloor, onChange }) {
  const [dialog, ask] = useConfirm();
  const [editing, setEditing] = useState(null); // program | "new" | null
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

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
  const remove = guard(async (p) => {
    const answer = await ask({
      icon: "bin",
      tone: "clay",
      title: `Remove "${p.name}"?`,
      points: [
        "Nothing it has already found is deleted — the grants stay in This week and in "
          + "your past findings.",
        "Future searches will stop looking for grants that match this program.",
      ],
      confirmLabel: "Remove this program",
    });
    if (!answer) return undefined;
    return api.programs.remove(p.id);
  });
  // Saving a card is a write plus a full dashboard refresh, so it is not instant — and
  // a Save button that stays live through it takes a second click and writes twice.
  const save = async (form) => {
    setSaving(true);
    setError(null);
    try {
      if (editing === "new") await api.programs.create(form);
      else await api.programs.update(editing.id, form);
      setEditing(null);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const activeCount = programs.filter((p) => p.active).length;
  const unfilled = programs.filter((p) => !p.summary && p.keywords.length === 0).length;

  const open = editing && editing !== "new" ? editing : null;

  return (
    // A panel, not a bare row. The chips used to float between the page head and the
    // blockers with no boundary of their own, which left the one control that decides
    // what a search is *for* reading as a caption on the heading above it.
    <section className="progbar">
      {dialog}

      <div className="progbar-head">
        <span className="progbar-mark" aria-hidden="true">
          <Icon name="check" size={13} />
        </span>
        <h2 className="progbar-title">What to search for</h2>
        <span className="muted small progbar-count">
          {activeCount} of {programs.length} being searched
        </span>
        {/* A pill at the head, not a text button at the end of the chips. On a long list
            the row wraps and "+ Add a program" lands wherever the last chip happened to
            stop, which is a different place every week. */}
        <button className="pill progbar-add" onClick={() => setEditing("new")}>
          + Add
        </button>
      </div>

      <div className="progbar-row">
        {programs.map((p) => (
          <Chip
            key={p.id}
            program={p}
            globalFloor={globalFloor}
            onToggle={toggle}
            onEdit={setEditing}
          />
        ))}
      </div>

      {activeCount === 0 && programs.length > 0 && (
        <p className="muted small progbar-note">
          Nothing is ticked, so a search would have nothing to look for.
        </p>
      )}

      {/* The other half of the same problem, which had no note at all: a card can be
          ticked-looking and still be unsearchable, and the only cue was a dashed border
          somebody has to already know the meaning of. */}
      {unfilled > 0 && (
        <p className="progbar-warn">
          <Icon name="warning" size={13} />
          A card with nothing in it can't be searched for — open it and paste the
          program's web page.
        </p>
      )}

      {error && <div className="notice error">{error}</div>}

      {/* The editor drops below the row rather than replacing a chip in it. Swapping a
          chip for a full form made the row reflow and the other chips jump, and on a
          wrapped row the form landed wherever that chip happened to sit. */}
      {editing && (
        <Editor
          key={open?.id || "new"}
          initial={open || BLANK}
          globalFloor={globalFloor}
          saving={saving}
          onSave={save}
          onCancel={() => setEditing(null)}
          onDelete={open ? () => remove(open) : null}
        />
      )}
    </section>
  );
}
