import { pacificStamp } from "../api";
import Icon from "./Icon";

// One line, always on screen: is the researcher on, when did it last run, what has it
// spent against the ceiling, and the way in to the knobs.
//
// The spend is not optional and not collapsible. CLAUDE.md caps a run at $1.00, and
// the whole product only works if the user trusts that — so the ceiling and the spend
// are here, not in a log file they would have to be shown how to find. This is the
// third of the correctness rules at the top of styles.css.
//
// **How the run ended is no longer on this strip.** It rendered directly underneath,
// four sections above the list it explains, and "why is this list short?" is a question
// asked at the list. `STOP_REASONS` moved to `pages/Dashboard.jsx` with it.

const DAY_LABEL = (d) => (d ? d[0].toUpperCase() + d.slice(1) + "s" : "");

// 0 -> "12am", 13 -> "1pm". Short, because it sits in a one-line strip.
const formatHour = (h) =>
  h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`;

export default function StatusStrip({
  enabled, run, ceiling, knobsOpen, onToggleKnobs, schedule, isRunning,
}) {
  const spent = run?.usd_spent || 0;
  const pct = Math.min(100, (spent / (ceiling || 1)) * 100);

  return (
    <section className="statusstrip">
        {/* The automation, and nothing else.

            This slot used to read "Fundworthy is on", which was true of every account
            that had ever existed and so told nobody anything — it reported `enabled`, a
            switch that is on unless an operator turns it off. The fact worth a permanent
            line is whether a search happens *without you*: "no search happened this week"
            and "no search is scheduled" are the same empty page and completely different
            situations.

            Paused still shows, because if it is ever true it is the only thing on this
            strip that matters. There is no longer a control for it here — see the
            recovery button on the dashboard's notice. */}
        {/* Three states, three weights, and the middle one is the point. `off` is the
            clay "something is wrong" treatment and belongs to Paused alone. Automatic
            search being off is the *default* — most accounts will never turn it on — so
            colouring it like a fault would put a warning on every new dashboard for a
            setting working exactly as intended. It reads as neutral information. */}
        <span className={`status-state ${
          !enabled ? "off" : schedule?.enabled ? "" : "idle"}`}>
          <span className="status-dot" aria-hidden="true" />
          {!enabled
            ? "Paused"
            : schedule?.enabled
              ? `Searches ${DAY_LABEL(schedule.day)}`
                + (schedule.hour != null ? ` at ${formatHour(schedule.hour)}` : "")
              : "Automatic search is off"}
        </span>

        <span className="status-sep" aria-hidden="true">|</span>

        <span className="status-item">
          Last search: <strong>{pacificStamp(run?.started_at)}</strong>
        </span>

        <span className="status-sep" aria-hidden="true">|</span>

        <span className="status-item">
          {/* Four decimals, not two. A run that cost $0.0043 rendered as "$0.00" reads
              as free, and the point of showing spend at all is that they can see the
              real number move. */}
          Spent <strong>${spent.toFixed(4)}</strong> of ${ceiling.toFixed(2)}
          {/* The figure moves during a search. Without a word on it, a number changing
              by itself every second and a half reads as a glitch rather than as the
              thing you are being asked to trust. */}
          {isRunning && <span className="status-live">Live</span>}
          <span
            className="minibar costbar"
            role="img"
            aria-label={`$${spent.toFixed(4)} of $${ceiling.toFixed(2)} spent`}
          >
            <span className="minibar-fill costbar-fill" style={{ width: `${pct}%` }} />
          </span>
        </span>

        <span className="status-actions">
          {/* Sliders, never a gear. This opens four numeric values you tune and it sits
              two panels away from the Settings nav item — two gears on one screen
              meaning different destinations is the confusion the split avoids. */}
          <button className="text status-knobs" onClick={onToggleKnobs} aria-expanded={knobsOpen}>
            <Icon name="sliders" size={14} />
            {knobsOpen ? "Hide search settings" : "Adjust search settings"}
          </button>
        </span>
    </section>
  );
}
