import { api } from "../api";
import Findings from "../components/Findings";
import Funders from "../components/Funders";
import Programs from "../components/Programs";
import RunPanel from "../components/RunPanel";

// The main page, in the order Mauri works: set up the search, then read the results.
//
// Findings come last rather than first on purpose. The whole premise of this project is
// that finding grants was never the bottleneck — deciding which are worth ten hours is.
// The controls that shape that decision belong above the list they produce.

export default function Dashboard({ state, onChange }) {
  const clear = state.clear || [];
  const needsCheck = state.needs_check || [];
  const total = clear.length + needsCheck.length;

  return (
    <>
      <header>
        <div className="panel-head">
          <h1>RISE funding finder</h1>
          {/* Top of the page, not down with the results. The findings list sits below
              the run panel, the programs and the funders, so a download button beside
              it is three screens from where someone goes looking for one.

              A plain <a download>, not a button with an onClick: the browser saves the
              file natively, so it still works if JavaScript fails elsewhere on the
              page, and there is no spinner state to get stuck in. */}
          {total > 0 && (
            <a className="button" href={api.exportUrl()} download>
              Download as a spreadsheet
            </a>
          )}
        </div>
        <p className="muted">
          Every opportunity here cleared your award floor. Nothing shows a number the
          agent could not find on the funder's own page.
        </p>
      </header>

      {!state.key_available && (
        <div className="notice">
          No Claude API key is saved yet, so searches will find and filter pages but will
          not read or score them. Add one on the <strong>Settings</strong> page.
        </div>
      )}

      {!state.has_api_key && state.api_key_source === "environment" && (
        <div className="notice">
          Scoring is running on a key from a <code>.env</code> file on this computer, not
          one saved in <strong>Settings</strong>. Fine for development — but RISE should
          save a key on the Settings page so it does not depend on that file.
        </div>
      )}

      <RunPanel
        settings={state.settings}
        sectors={state.sectors_available}
        latestRun={state.latest_run}
        running={state.running}
        onChange={onChange}
      />

      <Programs
        programs={state.programs}
        globalFloor={state.settings.min_award}
        onChange={onChange}
      />

      <Funders
        funders={state.funders}
        sectors={state.sectors_available}
        onChange={onChange}
      />

      <Findings
        clear={clear}
        needsCheck={needsCheck}
        emptyBody="Tick the programs you want searched, then press Re-run search pipeline."
      />
    </>
  );
}
