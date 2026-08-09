import Icon from "./Icon";
import { Busy } from "./Spinner";

// The weekly knobs. Folded away behind "Adjust search settings" in the status strip,
// because the user opens this page to read a list, not to change a floor they set in March.
//
// Collapsed, not deleted: these are the settings CLAUDE.md was reversed for. A
// spreadsheet cell cannot express "search these three programs, at this floor, this
// week", which is why the dashboard exists at all.

// The hint moves to `title` rather than a line of prose under every field. Four hints
// under four fields was about a third of the panel's height, restating labels that
// already say the same thing — and this panel sits over the findings it decides. Same
// reason the labels themselves are short nouns now rather than full sentences — "Award
// floor", not "Smallest award worth applying for" — with the full sentence surviving in
// the hint, not vanishing.
function Knob({ label, hint, children }) {
  return (
    <label className="field" title={hint || undefined}>
      <span>{label}</span>
      {children}
    </label>
  );
}

// A compact toggle for a setting that is real but rarely touched. An icon carries the
// idea at a glance and a short word keeps it nameable — R10 in Icon.jsx reserves
// icon-only for repeated, familiar row actions (edit, delete, copy); a schedule switch,
// an unbuilt discovery flag and Ultra mode are none of those, so they keep a word each
// rather than becoming three glyphs a no-AI-experience admin has to learn by heart. The
// full sentence that used to sit under each one as a `<small>` moves to `title`, the
// same trade Knob already makes above — that alone is most of what made three checkbox
// rows read as three paragraphs.
function ToggleChip({ icon, label, hint, checked, onChange }) {
  return (
    <label className={`togglechip ${checked ? "on" : ""}`} title={hint}>
      <input type="checkbox" checked={checked} onChange={onChange} />
      <Icon name={icon} size={14} />
      <span>{label}</span>
    </label>
  );
}

export default function SearchSettings({
  draft, set, dirty, saving, onSave, onUndo,
}) {
  return (
    <section className="searchpanel">
      <div className="knobs">
        <Knob
          label="Award floor ($)"
          hint="Smallest award worth applying for. Anything smaller is never shown to you."
        >
          <input
            type="number"
            step="1000"
            value={draft.min_award}
            onChange={(e) => set("min_award", Number(e.target.value))}
          />
        </Knob>

        <Knob
          label="Runway (days)"
          hint="Skip anything due within this many days — not enough time to apply otherwise."
        >
          <input
            type="number"
            value={draft.min_deadline_runway_days}
            onChange={(e) => set("min_deadline_runway_days", Number(e.target.value))}
          />
        </Knob>

        <Knob label="Result cap" hint="Most results to bring back. Sized for a one-hour review.">
          <input
            type="number"
            value={draft.max_opportunities}
            onChange={(e) => set("max_opportunities", Number(e.target.value))}
          />
        </Knob>

        <Knob
          label="Spend limit ($)"
          hint="Most to spend on one search. It stops itself before going over."
        >
          <input
            type="number"
            step="0.25"
            value={draft.run_budget_usd}
            onChange={(e) => set("run_budget_usd", Number(e.target.value))}
          />
        </Knob>

        {/* Moved here from the Organization panel — this decides part of the score
            (agent/score.py: WEIGHTS["timing"]), the same as the other four knobs in
            this row, not a fact about who the org is. */}
        <Knob
          label="Hours per app"
          hint="Hours you can spend on one application. A grant that would cost more than this scores lower on timing."
        >
          <input
            type="number"
            min="1"
            max="200"
            value={draft.max_effort_hours}
            onChange={(e) => set("max_effort_hours", Number(e.target.value))}
          />
        </Knob>
      </div>

      {/* "Where to look" — four sector checkboxes — used to sit here, and it is gone
          rather than restyled (R8).

          The copy under it admitted the problem: "These are our best guess at the
          categories." A funder's bucket came from the shipped registry or defaulted to
          "foundation" for anything typed in, so unticking a box excluded funders on a
          label nobody at the nonprofit had chosen — silently, in the free tier, where
          nothing explains itself. `sources_from_db` no longer narrows by it either.

          `sectors_active` stays in the schema and the API so old rows still read back.
          Which funders get searched is the funder list: pause, block, delete. */}

      <div className="searchpanel-foot compact">
        {/* Grouped in one wrapper so `.searchpanel-foot`'s space-between treats the
            three chips as a single cluster on the left, not three items spread evenly
            across the whole row — the same job `.row`'s own margin-left:auto does for
            Undo/Save on the right. Three switches that used to be three paragraphs — a
            checkbox, a full sentence, then a `<small>` restating it with the one detail
            that mattered buried at the end. Same fix as the knobs above: the full
            sentence survives in `title`, not on screen. See ToggleChip and R10 in
            Icon.jsx for why these keep a word each rather than becoming bare glyphs. */}
        <div className="togglechips">
          <ToggleChip
            icon="clock"
            label="Weekly"
            hint="Search automatically every week — off by default. You can always search by hand with the button above."
            checked={draft.schedule_enabled}
            onChange={(e) => set("schedule_enabled", e.target.checked)}
          />

          <ToggleChip
            icon="globe"
            label="Beyond your list"
            hint="Also look beyond the funders on your list — being built; for now this searches your list only."
            checked={draft.search_beyond_partners}
            onChange={(e) => set("search_beyond_partners", e.target.checked)}
          />

          {/* Off by default, deliberately: CLAUDE.md's whole premise is that a short
              list is a feature, not a shortfall, and this one switch abandons that on
              purpose for someone who has decided they would rather spend the whole
              budget than stop at "most results to bring back" above. It does not
              reach further than your funder list already does — a short list still
              tops out at what's on it, whatever this is set to. */}
          <ToggleChip
            icon="zap"
            label="Ultra mode"
            hint={
              'Spend the whole search budget — ignores "result cap" above and keeps ' +
              "scoring until the budget or your funder list runs out."
            }
            checked={draft.ultra_mode}
            onChange={(e) => set("ultra_mode", e.target.checked)}
          />
        </div>

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
