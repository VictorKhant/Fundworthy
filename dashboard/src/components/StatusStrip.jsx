import { pacificStamp } from "../api";

// One line, always on screen: is the researcher on, when did it last run, what has it
// spent against the ceiling, and the way in to the knobs.
//
// The spend is not optional and not collapsible. CLAUDE.md caps a run at $1.00, and
// the whole product only works if the user trusts that — so the ceiling, the spend, and the
// reason the run stopped are here, not in a log file they would have to be shown how to
// find. This is the third of the correctness rules at the top of styles.css.

const STOP_REASONS = {
  target_met: "Found enough for this week and stopped.",
  budget: "Hit the spending limit and stopped rather than going over.",
  sources_exhausted:
    "Checked every funder on your list. Nothing new above your award floor is a "
    + "normal week, not a fault.",
  disabled: "The researcher is switched off.",
  stopped_by_user: "You stopped it.",
  error: "Something went wrong — the log below says what.",
  partial: "Something broke part-way through. What it had already found is above.",
  // The two that used to be indistinguishable from a quiet week. Both mean the search
  // could not have worked, and both name the one thing to change.
  no_api_key:
    "Stopped before reading anything: there was no Claude API key to read with. "
    + "Add one on Settings.",
  no_funders:
    "Stopped without reading anything: there were no funders to search. Fundworthy "
    + "only reads the funders on your list — add some on Discover funders.",
};

export default function StatusStrip({ enabled, run, ceiling, knobsOpen, onToggleKnobs }) {
  const spent = run?.usd_spent || 0;
  const pct = Math.min(100, (spent / (ceiling || 1)) * 100);

  // One broken funder and a genuinely quiet week both produce a short list. Saying which
  // is the difference between a list they can trust and one they have to re-check by hand.
  const broken = (run?.source_health || []).filter(
    (h) => h.status === "unreachable" || h.status === "unparseable"
  );

  return (
    <>
      <section className="statusstrip">
        <span className={`status-state ${enabled ? "" : "off"}`}>
          <span className="status-dot" aria-hidden="true" />
          {enabled ? "Researcher is on" : "Researcher is off"}
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
          <span
            className="minibar costbar"
            role="img"
            aria-label={`$${spent.toFixed(4)} of $${ceiling.toFixed(2)} spent`}
          >
            <span className="minibar-fill costbar-fill" style={{ width: `${pct}%` }} />
          </span>
        </span>

        <span className="status-actions">
          <button className="text" onClick={onToggleKnobs} aria-expanded={knobsOpen}>
            {knobsOpen ? "Hide search settings" : "Adjust search settings"}
          </button>
        </span>
      </section>

      {run?.stop_reason && (
        <p className="status-note muted small">
          {STOP_REASONS[run.stop_reason] || run.stop_reason}
          {run.duplicates_skipped > 0 &&
            ` Skipped ${run.duplicates_skipped} you have already seen this month, for free.`}
        </p>
      )}

      {broken.length > 0 && (
        <div className="notice plain">
          Some funders could not be checked this time, so this list may be short for that
          reason rather than because there was nothing to find:{" "}
          {broken.map((h) => h.funder).join(", ")}.
        </div>
      )}
    </>
  );
}
