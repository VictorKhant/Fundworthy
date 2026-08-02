import { SECTOR_LABELS } from "../api";

// The weekly knobs. Folded away behind "Adjust search settings" in the status strip,
// because Mauri opens this page to read a list, not to change a floor she set in March.
//
// Collapsed, not deleted: these are the settings CLAUDE.md §3 was reversed for. A
// spreadsheet cell cannot express "search these three programs, at this floor, this
// week", which is why the dashboard exists at all.

function Knob({ label, hint, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export default function SearchSettings({
  draft, set, sectors, dirty, saving, onSave, onUndo,
}) {
  const toggleSector = (s) => {
    const active = draft.sectors_active.includes(s)
      ? draft.sectors_active.filter((x) => x !== s)
      : [...draft.sectors_active, s];
    set("sectors_active", active);
  };

  return (
    <section className="searchpanel">
      <div className="knobs">
        <Knob
          label="Smallest award worth applying for"
          hint="Anything smaller is never shown to you."
        >
          <input
            type="number"
            step="1000"
            value={draft.min_award}
            onChange={(e) => set("min_award", Number(e.target.value))}
          />
        </Knob>

        <Knob label="Skip anything due within (days)" hint="Not enough time to apply otherwise.">
          <input
            type="number"
            value={draft.min_deadline_runway_days}
            onChange={(e) => set("min_deadline_runway_days", Number(e.target.value))}
          />
        </Knob>

        <Knob label="Most results to bring back" hint="Sized for a one-hour review.">
          <input
            type="number"
            value={draft.max_opportunities}
            onChange={(e) => set("max_opportunities", Number(e.target.value))}
          />
        </Knob>

        <Knob label="Most to spend on one search ($)" hint="It stops itself before going over.">
          <input
            type="number"
            step="0.25"
            value={draft.run_budget_usd}
            onChange={(e) => set("run_budget_usd", Number(e.target.value))}
          />
        </Knob>
      </div>

      <div className="field">
        <span>Where to look</span>
        <div className="checks">
          {sectors.map((s) => (
            <label key={s} className="check">
              <input
                type="checkbox"
                checked={draft.sectors_active.includes(s)}
                onChange={() => toggleSector(s)}
              />
              {SECTOR_LABELS[s] || s}
            </label>
          ))}
        </div>
        <small className="muted">
          These are our best guess at the categories. Tell us the four you actually care
          about and we will rename them.
        </small>
      </div>

      <label className="field inline">
        <input
          type="checkbox"
          checked={draft.search_beyond_partners}
          onChange={(e) => set("search_beyond_partners", e.target.checked)}
        />
        <span>
          Also look beyond the funders on my list
          <small className="muted"> — being built; for now this searches your list only</small>
        </span>
      </label>

      <div className="searchpanel-foot">
        <label className="check">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
          />
          The researcher is switched on — it searches every Wednesday night
        </label>

        <div className="row">
          {dirty && (
            <button className="text" onClick={onUndo}>
              Undo changes
            </button>
          )}
          <button className="dark" onClick={onSave} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      </div>
    </section>
  );
}
