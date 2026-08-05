import { useEffect, useState } from "react";
import { api, money } from "../api";
import DownloadCsv from "../components/DownloadCsv";
import Findings from "../components/Findings";
import Programs from "../components/Programs";
import RunLog from "../components/RunLog";
import SearchSettings from "../components/SearchSettings";
import StatusStrip from "../components/StatusStrip";
import { useRun } from "../useRun";

// "This week" — the page the user opens on Thursday morning.
//
// The findings moved to the top in this pass. The old order put the controls above the
// list they produce, which was the right instinct and the wrong execution: it meant four
// screens of knobs before the thing they came to read. The controls are still above the
// list, condensed into one always-visible status strip; the knobs themselves fold away
// behind it, because a floor set in March does not need re-reading every week.
//
// Programs and funders drop to the bottom for the same reason — they are setup, and
// setup is not what a Thursday is for.

const HELPER_KEY = "fw.helperDismissed";

export default function Dashboard({ state, onChange }) {
  const clear = state.clear || [];
  const needsCheck = state.needs_check || [];
  const total = clear.length + needsCheck.length;

  const [draft, setDraft] = useState(state.settings);
  const [knobsOpen, setKnobsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [helperDismissed, setHelperDismissed] = useState(
    () => localStorage.getItem(HELPER_KEY) === "1"
  );

  useEffect(() => setDraft(state.settings), [state.settings]);

  const { live, run, isRunning, start, stop, error: runError } = useRun({
    latestRun: state.latest_run,
    running: state.running,
    onChange,
  });

  const dirty = JSON.stringify(draft) !== JSON.stringify(state.settings);
  const set = (k, v) => setDraft({ ...draft, [k]: v });

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      await api.settings.save(draft);
      await onChange();
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  }

  function dismissHelper() {
    localStorage.setItem(HELPER_KEY, "1");
    setHelperDismissed(true);
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>This week</h1>
          <p className="muted small">
            {total === 0
              ? "Nothing found yet this month."
              : `${total} ${total === 1 ? "opportunity" : "opportunities"} found · every one cleared your ${money(state.settings.min_award)} floor`}
          </p>
        </div>

        <div className="row">
          {total > 0 && <DownloadCsv />}
          {isRunning ? (
            <button className="danger" onClick={stop}>
              Stop the search
            </button>
          ) : (
            <button
              className="primary"
              onClick={() => start(dirty ? () => api.settings.save(draft) : null)}
              disabled={!draft.enabled}
            >
              Search again now
            </button>
          )}
        </div>
      </header>

      {!helperDismissed && (
        <div className="helper">
          <span className="helper-mark" aria-hidden="true">✳</span>
          <p>
            New here? The list below is what the researcher found this week. Open one to
            see why it scored the way it did — anything marked <strong>AI</strong> is the
            researcher's judgement, everything else is quoted from the funder's page.
          </p>
          <button className="text helper-dismiss" onClick={dismissHelper}>
            Dismiss
          </button>
        </div>
      )}

      {!state.key_available && (
        <div className="notice plain">
          No Claude API key is saved yet, so searches will find and filter pages but will
          not read or score them. Add one on the <strong>Settings</strong> page.
        </div>
      )}

      {!state.has_api_key && state.api_key_source === "environment" && (
        <div className="notice plain">
          Scoring is running on a key from a <code>.env</code> file on this computer, not
          one saved in <strong>Settings</strong>. Fine for development — but save a key on
          the Settings page so it does not depend on that file.
        </div>
      )}

      {!draft.enabled && (
        <div className="notice plain">
          The researcher is switched off. Turn it back on under "Adjust search settings"
          before running a search.
        </div>
      )}

      {(runError || saveError) && <div className="notice error">{runError || saveError}</div>}

      <StatusStrip
        enabled={draft.enabled}
        run={run}
        ceiling={draft.run_budget_usd || 1}
        knobsOpen={knobsOpen}
        onToggleKnobs={() => setKnobsOpen(!knobsOpen)}
      />

      {knobsOpen && (
        <SearchSettings
          draft={draft}
          set={set}
          sectors={state.sectors_available}
          dirty={dirty}
          saving={saving}
          onSave={save}
          onUndo={() => setDraft(state.settings)}
        />
      )}

      {(isRunning || live.log?.length > 0) && (
        <RunLog isRunning={isRunning} log={live.log} />
      )}

      <Findings
        clear={clear}
        needsCheck={needsCheck}
        emptyBody='Tick the programs you want searched below, then press "Search again now".'
      />

      {/* Setup, at the bottom. Two columns on a desk, one on a laptop. */}
      <div className="paircols">
        <Programs
          programs={state.programs}
          globalFloor={state.settings.min_award}
          onChange={onChange}
        />
      </div>
    </>
  );
}
