import { SECTOR_LABELS } from "../api";
import { Busy } from "./Spinner";

// The weekly knobs. Folded away behind "Adjust search settings" in the status strip,
// because the user opens this page to read a list, not to change a floor they set in March.
//
// Collapsed, not deleted: these are the settings CLAUDE.md was reversed for. A
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
        {/* Two switches, and separating them was the point.

            One checkbox used to be both the §8 kill switch and "does a search happen on
            a schedule". Unticking it to stop the weekly job also greyed out "Search again
            now" — so an org that simply wanted to run searches by hand, when they felt
            like it, could not run one at all. Nobody would guess that from the label. */}
        <label className="check">
          <input
            type="checkbox"
            checked={draft.schedule_enabled}
            onChange={(e) => set("schedule_enabled", e.target.checked)}
          />
          Search automatically every week
          <small className="muted">
            {" "}— off by default. You can always search by hand with the button above.
          </small>
        </label>

        {/* This used to read "it searches every Wednesday night", which was a sentence
            rather than a setting: nothing scheduled anything, and the only way a search
            happened was somebody pressing Re-run. Now it is three controls and there is
            a scheduler behind them. Local time, because "before the Thursday meeting" is
            what people actually mean. */}
        {draft.schedule_enabled && (
          <div className="schedule">
            <span className="muted small">Search automatically every</span>
            <select value={draft.schedule_day}
                    onChange={(e) => set("schedule_day", e.target.value)}>
              {["monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"].map((d) => (
                <option key={d} value={d}>
                  {d[0].toUpperCase() + d.slice(1)}
                </option>
              ))}
            </select>
            <span className="muted small">at</span>
            <select value={String(draft.schedule_hour)}
                    onChange={(e) => set("schedule_hour", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {h === 0 ? "12 midnight"
                    : h < 12 ? `${h} am`
                    : h === 12 ? "12 noon"
                    : `${h - 12} pm`}
                </option>
              ))}
            </select>
            <select value={draft.schedule_timezone}
                    onChange={(e) => set("schedule_timezone", e.target.value)}>
              {[
                ["America/Los_Angeles", "Pacific"],
                ["America/Denver", "Mountain"],
                ["America/Chicago", "Central"],
                ["America/New_York", "Eastern"],
                ["America/Anchorage", "Alaska"],
                ["Pacific/Honolulu", "Hawaii"],
              ].map(([tz, label]) => (
                <option key={tz} value={tz}>{label}</option>
              ))}
            </select>
            <p className="muted small">
              Findings will be waiting the next morning. If the server is down at that
              hour the search runs as soon as it is back — you get the week's search
              either way, and never two of them.
            </p>
          </div>
        )}

        {/* There is deliberately no "pause everything" control here.

            `enabled` still exists and still stops every search — it is the §8 kill switch
            and the CLI and `FUNDWORTHY_STRICT_CONFIG` depend on it. It just is not a
            thing to offer somebody next to the schedule, because the two read as
            alternatives and they are not: one means "don't search on Wednesdays" and the
            other means "this app does nothing now". Pausing is what the automation
            checkbox above is for; not searching is what not pressing the button is for.

            Nobody can get stranded by its absence: if `enabled` is ever false the
            dashboard says so and offers a button to undo it. */}

        <div className="row">
          {dirty && (
            <button className="text" onClick={onUndo}>
              Undo changes
            </button>
          )}
          <Busy className="dark" busy={saving} busyLabel="Saving"
                onClick={onSave} disabled={!dirty}>
            Save settings
          </Busy>
        </div>
      </div>
    </section>
  );
}
