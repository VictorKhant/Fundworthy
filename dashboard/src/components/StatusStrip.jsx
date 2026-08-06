import { pacificStamp } from "../api";

// One line, always on screen: is the researcher on, when did it last run, what has it
// spent against the ceiling, and the way in to the knobs.
//
// The spend is not optional and not collapsible. CLAUDE.md caps a run at $1.00, and
// the whole product only works if the user trusts that — so the ceiling, the spend, and the
// reason the run stopped are here, not in a log file they would have to be shown how to
// find. This is the third of the correctness rules at the top of styles.css.

// How the last search ended, in one line. `ok` decides the colour of the marker: sage for
// "this is a normal outcome", clay for "something needs you". Nothing here is an error
// dialog — a search that finds nothing is the product working — but a search that could
// not run should not look the same as one that ran and found a quiet week.
const STOP_REASONS = {
  target_met: { ok: true, text: "Found enough for this week and stopped." },
  sources_exhausted: { ok: true, text: "Checked every funder on your list." },
  budget: { ok: false, text: "Hit your spending limit and stopped rather than going over." },
  disabled: { ok: false, text: "The researcher is switched off." },
  stopped_by_user: { ok: true, text: "You stopped it." },
  error: { ok: false, text: "Something went wrong — the log below says what." },
  partial: { ok: false, text: "Something broke part-way through. What it had already found is above." },
  // The two that used to be indistinguishable from a quiet week. Both mean the search
  // could not have worked, and both name the one thing to change.
  no_api_key: {
    ok: false,
    text: "Stopped before reading anything — there was no Claude API key to read with. "
      + "Add one on Settings.",
  },
  no_funders: {
    ok: false,
    text: "Stopped without reading anything — there were no funders to search. "
      + "Fundworthy only reads the funders on your list.",
  },
};

const DAY_LABEL = (d) => (d ? d[0].toUpperCase() + d.slice(1) + "s" : "");

// 0 -> "12am", 13 -> "1pm". Short, because it sits in a one-line strip.
const formatHour = (h) =>
  h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`;

export default function StatusStrip({
  enabled, run, ceiling, knobsOpen, onToggleKnobs, schedule,
}) {
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

      {/* How the last search ended. This was `muted small` — grey 13px fine print,
          indistinguishable from every other muted line on the page, and set in a
          stylesheet rule that carried nothing but a margin.

          It is the answer to the question somebody actually arrives with on a thin
          Thursday: *why is this list short?* "Checked every funder on your list" and
          "there was no API key to read with" are completely different answers and only
          one of them is a problem, so it now has a marker whose colour says which, and
          text you can read without hunting for it. */}
      {run?.stop_reason && (() => {
        const outcome = STOP_REASONS[run.stop_reason];
        return (
          <p className={`run-outcome ${outcome && !outcome.ok ? "attention" : ""}`}>
            <span className="run-outcome-dot" aria-hidden="true" />
            <span>
              {outcome ? outcome.text : run.stop_reason}
              {run.duplicates_skipped > 0 && (
                <span className="muted">
                  {" "}Skipped {run.duplicates_skipped} you have already seen this month,
                  for free.
                </span>
              )}
            </span>
          </p>
        );
      })()}

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
