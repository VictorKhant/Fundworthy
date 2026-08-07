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
//
// Two things sit **against the list** rather than near the top, and both moved for the
// same reason: they answer questions that are asked at the list.
//
//   - the outcome line ("Checked every funder on your list · skipped 12 you have already
//     seen") used to render inside StatusStrip, four sections above the thing it
//     explains. It is the answer to *why is this list short?*
//   - the helper banner used to be the first element under the page head — the spot the
//     eye lands on — explaining a convention (the AI/sourced split) that the findings
//     already mark inline on every row.

const HELPER_KEY = "fw.helperDismissed";

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

// The run's own notes, minus its bookkeeping.
//
// `run.notes` is where the pipeline writes anything it wants a person to know — a ticked
// program that matched no California funding category and so searched nothing, a budget
// ceiling, a model call that failed on every page. **None of it was rendered anywhere.**
// It reached `/api/state` as `latest_run.notes` and stopped, so the one place a run
// explains itself was invisible, and a search that broke identically 164 times looked
// the same as a quiet week.
//
// Two shapes are dropped because the stage boxes already say it better, and only those
// two — an unrecognised note is SHOWN. That direction is deliberate: a new note that
// nobody thought to whitelist should look noisy, never be swallowed. Note that
// "Sources: shipped registry (could not read the funders list…)" is not matched by the
// first pattern and is therefore shown, which is the whole point — it is the one
// "Sources:" line that means something went wrong.
const ROUTINE_NOTE = [
  /^Sources: \d+ from the funders list/,
  /^Remove list: \d+ funder/,
];
const worthReading = (notes) =>
  (notes || []).filter((n) => !ROUTINE_NOTE.some((re) => re.test(n)));

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
  const [logOpen, setLogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [helperDismissed, setHelperDismissed] = useState(
    () => localStorage.getItem(HELPER_KEY) === "1"
  );

  // By VALUE, not by reference. `state.settings` is a fresh object literal on every
  // poll response — same shape as `dirty` below, which has to make the same comparison
  // for the same reason. Depending on the reference itself reset unsaved knob edits on
  // any unrelated poll tick (ticking a program chip elsewhere on the page was enough),
  // silently, mid-edit, with no warning — the settings just snapped back.
  useEffect(() => setDraft(state.settings), [JSON.stringify(state.settings)]);

  const { live, run, isRunning, start, stop, error: runError } = useRun({
    latestRun: state.latest_run,
    running: state.running,
    onChange,
  });

  // The log opens itself when a search starts, and can then be closed. It used to be a
  // `<details open={isRunning}>`, which forces it open for the whole run — the one
  // stretch of time somebody might want it out of the way, now that the three boxes
  // above say what is happening.
  //
  // Below `useRun` and not above it: the dependency array is evaluated during the render
  // that declares `isRunning`, so reading it earlier is a temporal-dead-zone
  // ReferenceError rather than an undefined.
  useEffect(() => { if (isRunning) setLogOpen(true); }, [isRunning]);

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
        isRunning={isRunning}
        ceiling={draft.run_budget_usd || 1}
        knobsOpen={knobsOpen}
        onToggleKnobs={() => setKnobsOpen(!knobsOpen)}
      />

      {knobsOpen && (
        <SearchSettings
          draft={draft}
          set={set}
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
          argument: free, cheap, expensive.

          Mounted through a run, not hidden for it. They used to appear only once a
          search had finished, on the reasoning that last week's funnel above a live log
          would read as this run's progress. It would have — so the boxes show *this*
          run's progress instead, which is what they were asked for in the first place. */}
      {run && (
        <Stages
          run={run}
          isRunning={isRunning}
          cap={draft.max_opportunities}
          settings={state.settings}
          choices={state.model_choices || {}}
          defaults={state.model_defaults || {}}
          logOpen={logOpen}
          onToggleLog={() => setLogOpen(!logOpen)}
          onChange={onChange}
        />
      )}

      {/* The log is kept verbatim, opened by the button in the stage header above rather
          than by a <summary> of its own further down the page. It is still the only thing
          that explains a run that died halfway, so it stays reachable — and it opens
          automatically while a run is going, because the boxes say what is happening and
          this says what is happening to it. */}
      {logOpen && (isRunning || live.log?.length > 0) && (
        <div className="runlog-open">
          <RunLog isRunning={isRunning} log={live.log} />
        </div>
      )}

      {/* How the last search ended, against the list it explains.
          "Checked every funder on your list" and "there was no API key to read with" are
          completely different answers to *why is this list short?*, and only one of them
          is a problem — so the marker's colour says which. */}
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

      {/* What the search itself reported, in its own words. Below the outcome line
          because the outcome is the headline and this is the detail behind it. */}
      {worthReading(run?.notes).length > 0 && (
        <div className="run-notes">
          <p className="run-notes-head">What this search reported</p>
          <ul>
            {worthReading(run.notes).map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      {/* "Nothing to review" has several very different causes and used to have one
          sentence. A search that ran and filtered everything out is a real, ordinary
          week; a search that never ran because nothing was set up is not, and telling
          somebody to "tick the programs below" when the actual problem is a missing API
          key sends them to fix the wrong thing. */}
      <Findings
        clear={clear}
        needsCheck={needsCheck}
        emptyBody={emptyBody()}
        maxEffortHours={state.settings.max_effort_hours}
        helper={!helperDismissed && (
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
      />

    </>
  );
}
