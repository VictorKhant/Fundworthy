import { useEffect, useState } from "react";
import { api, money } from "../api";
import DownloadCsv from "../components/DownloadCsv";
import Findings from "../components/Findings";
import Programs from "../components/Programs";
import RunLog from "../components/RunLog";
import Stages from "../components/Stages";
import SearchSettings from "../components/SearchSettings";
import { Busy } from "../components/Spinner";
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

// The page a blocker sends you to, named the way the sidebar names it.
const PAGE_LABEL = {
  settings: "Open Settings",
  discover: "Open Discover funders",
  dashboard: null,      // already here; the fix is on this page
};

export default function Dashboard({ state, onChange, onGoto }) {
  const clear = state.clear || [];
  const needsCheck = state.needs_check || [];
  const total = clear.length + needsCheck.length;

  const [draft, setDraft] = useState(state.settings);
  const [knobsOpen, setKnobsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
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

  // Why a search would not work, straight from the server — the same list, in the same
  // words, that pressing the button would have failed with. Pressing it used to be the
  // only way to find out: the run started, crawled politely for five to ten minutes, and
  // came back with an empty list and no explanation on it.
  //
  // The kill switch gets two exceptions, both because it is the one blocker whose fix is
  // a control on this very page. It is dropped from the list if the switch has been
  // ticked back on but not yet saved — pressing Search writes the draft first, so by the
  // time the server sees the request it is on — and it is never *shown* as a blocker,
  // because it already has its own notice below and its own toggle in the knobs.
  const pending = (state.blockers || []).filter(
    (b) => b.code !== "disabled" || !draft.enabled
  );
  const blockers = pending.filter((b) => b.code !== "disabled");
  const blocked = pending.length > 0;

  async function searchNow() {
    setStarting(true);
    try {
      await start(dirty ? () => api.settings.save(draft) : null);
    } finally {
      setStarting(false);
    }
  }

  // What "nothing here" means this week, which depends entirely on what happened. The
  // three cases read almost identically on screen and could not be more different: not
  // set up, ran and found nothing, never run.
  //
  // Deliberately does NOT restate how the run ended — the outcome line above the list
  // says that now, and says it in a colour. This is the part the outcome line cannot
  // carry: how much was looked at, and the one knob that would widen it.
  function emptyBody() {
    if (blocked) return pending[0].message;
    if (!state.latest_run) {
      return 'Nothing has been searched yet. Press "Search again now" — it takes a few '
        + "minutes and costs about a dollar of your own Claude credit.";
    }
    const rejected = state.latest_run.rejected_by_filter || {};
    const count = Object.values(rejected).reduce((a, b) => a + b, 0);
    if (count > 0) {
      return `${count} page${count === 1 ? " was" : "s were"} set aside — below your `
        + `${money(state.settings.min_award)} floor, past their deadline, or already `
        + "shown to you this month. Nothing cleared the bar, which is a normal week. "
        + 'Lower the floor under "Adjust search settings" to see more.';
    }
    return "Nothing new cleared your floor. That is a normal week — Fundworthy would "
      + "rather show you six worth applying for than sixty that are not.";
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(state.settings);
  const set = (k, v) => setDraft({ ...draft, [k]: v });

  // `next` lets a caller save a value it has just computed. Without it the only thing
  // savable is `draft`, and a `set(...)` immediately before a `save()` does not reach it —
  // React has not re-rendered yet, so the closure still holds the previous draft and the
  // change is written on some later save or not at all.
  //
  // Returns whether it worked, because the caller may want to do something afterwards
  // (the knobs panel closes itself) and that must not happen when the save failed.
  async function save(next) {
    const body = next || draft;
    setSaving(true);
    setSaveError(null);
    try {
      await api.settings.save(body);
      await onChange();
      return true;
    } catch (e) {
      setSaveError(e.message);
      return false;
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
            <Busy
              className="primary"
              busy={starting}
              busyLabel="Starting the search"
              onClick={searchNow}
              disabled={blocked}
              // The greyed-out button is not self-explanatory, so it says why on hover
              // as well as in the blocker list below it.
              title={blocked ? pending[0].message : undefined}
            >
              Search again now
            </Busy>
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

      {/* Which programs this week's search is for. At the TOP, because it is a
          question you answer before reading results rather than after — it used to be a
          list of full-width rows at the foot of the page, below the findings it decides
          the shape of. */}
      <Programs
        programs={state.programs}
        globalFloor={state.settings.min_award}
        onChange={onChange}
      />

      {/* Everything standing between this org and a working search, each with the page
          that fixes it. The two notices this replaced said what was missing but not what
          it meant, and there was nothing at all for the two commonest causes of an empty
          result — an empty funder list and no ticked program. */}
      {blockers.length > 0 && (
        <div className="blockers">
          {blockers.map((b) => (
            <div key={b.code} className="blocker">
              <p>{b.message}</p>
              {PAGE_LABEL[b.page] && onGoto && (
                <button onClick={() => onGoto(b.page)}>{PAGE_LABEL[b.page]}</button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* The one place `enabled` is reachable from the UI, and it only appears when it is
          the thing standing in your way.

          There is no "pause everything" checkbox any more — it read as an alternative to
          the schedule when it is nothing of the sort. But the setting still exists, an
          operator or an older account can hold it, and a greyed-out button with no
          control anywhere to ungrey it would be a dead end. So the control lives here,
          shown only when it is false: an off switch you cannot reach until you have
          already hit it. */}
      {!draft.enabled && (
        <div className="blocker">
          <p>
            Fundworthy is paused, so nothing runs and nothing is spent — by hand or on a
            schedule.
          </p>
          <Busy
            busy={saving}
            busyLabel="Starting"
            onClick={() => { set("enabled", true); save({ ...draft, enabled: true }); }}
          >
            Turn it back on
          </Busy>
        </div>
      )}

      {/* Not a problem — a note about which key is paying, and only when the answer is
          surprising. It used to read as a warning ("save a key on the Settings page so it
          does not depend on that file") on a screen where nothing was wrong, which put a
          developer's convenience in front of a user as a chore.

          Only ever reachable on a local install now: once sign-in is configured the
          environment key stops resolving at all, so nobody signing in to a deployed
          Fundworthy can see this. */}
      {state.api_key_source === "environment" && (
        <div className="notice plain small">
          Local install — reading with the <code>ANTHROPIC_API_KEY</code> from this
          machine's <code>.env</code>. Save one under <strong>Settings</strong> and that
          one is used instead.
        </div>
      )}

      {(runError || saveError) && <div className="notice error">{runError || saveError}</div>}

      <StatusStrip
        enabled={draft.enabled}
        schedule={{
          enabled: draft.schedule_enabled,
          day: draft.schedule_day,
          hour: draft.schedule_hour,
        }}
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
          // Wrapped, not passed: `onSave` is wired straight to a button's onClick, so
          // handing over `save` itself would call save(MouseEvent) — and now that save
          // takes an optional body, that event would become the body.
          //
          // Saving closes the panel. These are settings you change and then get on with
          // reading the week's list, and leaving four screens of knobs open over the
          // thing they produce gives no signal that the save landed — the button just
          // greys out again. Only on success: a failed save keeps the panel open, with
          // the error and the edits that caused it still on screen.
          onSave={async () => { if (await save()) setKnobsOpen(false); }}
          onUndo={() => setDraft(state.settings)}
        />
      )}

      {/* What the search did, as three boxes — the cost order, which is also the
          argument: free, cheap, expensive. Hidden while a run is going, because the
          numbers are the *finished* run's and showing last week's funnel above a live
          log reads as this run's progress. */}
      {!isRunning && state.latest_run && (
        <Stages
          run={state.latest_run}
          settings={state.settings}
          choices={state.model_choices || {}}
          defaults={state.model_defaults || {}}
          onChange={onChange}
        />
      )}

      {/* The log is kept verbatim and moved behind a disclosure. It is still the only
          thing that explains a run that died halfway, so it stays reachable — and it
          opens automatically while a run is going, because during a run it is the only
          thing there is to watch. */}
      {(isRunning || live.log?.length > 0) && (
        <details className="runlog-details" open={isRunning}>
          <summary>Show the technical log</summary>
          <RunLog isRunning={isRunning} log={live.log} />
        </details>
      )}

      {/* "Nothing to review" has several very different causes and used to have one
          sentence. A search that ran and filtered everything out is a real, ordinary
          week; a search that never ran because nothing was set up is not, and telling
          somebody to "tick the programs below" when the actual problem is a missing API
          key sends them to fix the wrong thing. */}
      <Findings clear={clear} needsCheck={needsCheck} emptyBody={emptyBody()} />

    </>
  );
}
