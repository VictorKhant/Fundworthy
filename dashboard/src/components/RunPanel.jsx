import { useEffect, useRef, useState } from "react";
import { api, money, SECTOR_LABELS } from "../api";

// The weekly knobs and the "Re-run search pipeline" button.
//
// Two things this panel is careful about:
//
//   Cost is never hidden. §8 caps a run at $1.00 and the whole product only works if
//   Mauri trusts that. So the ceiling, the spend, and the reason the run stopped are on
//   screen, not in a log file she would have to be shown how to find.
//
//   A running search is legible. It polls and streams the agent's own output, because
//   a button that goes quiet for four minutes reads as broken, and the honest fix is to
//   show the work rather than to fake a progress bar.

const STOP_REASONS = {
  target_met: "Found enough for this week and stopped.",
  budget: "Hit the spending limit and stopped rather than going over.",
  sources_exhausted: "Checked every funder on your list.",
  disabled: "The agent is switched off in Settings.",
  stopped_by_user: "You stopped it.",
  error: "Something went wrong — the log below says what.",
};

function Knob({ label, hint, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export default function RunPanel({ settings, sectors, latestRun, running, onChange }) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [live, setLive] = useState({ running, run: latestRun, log: [] });
  const logRef = useRef(null);

  useEffect(() => setDraft(settings), [settings]);

  // Poll only while something is actually running.
  useEffect(() => {
    if (!live.running && !running) return undefined;
    const id = setInterval(async () => {
      try {
        const next = await api.runs.current();
        setLive(next);
        if (!next.running) {
          clearInterval(id);
          onChange();
        }
      } catch {
        /* the poll failing is not worth showing; the next tick retries */
      }
    }, 1500);
    return () => clearInterval(id);
  }, [live.running, running]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [live.log]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  const set = (k, v) => setDraft({ ...draft, [k]: v });

  const toggleSector = (s) => {
    const active = draft.sectors_active.includes(s)
      ? draft.sectors_active.filter((x) => x !== s)
      : [...draft.sectors_active, s];
    set("sectors_active", active);
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save(draft);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function start() {
    setError(null);
    try {
      if (dirty) await api.settings.save(draft);
      await api.runs.start({});
      setLive({ running: true, run: null, log: ["Starting the search…"] });
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  }

  async function stop() {
    try {
      await api.runs.stop();
    } catch (e) {
      setError(e.message);
    }
  }

  const run = live.run || latestRun;
  const isRunning = live.running || running;
  const ceiling = draft.run_budget_usd || 1;
  const spent = run?.usd_spent || 0;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>This week's search</h2>
        {isRunning ? (
          <button className="danger" onClick={stop}>
            Stop the search
          </button>
        ) : (
          <button className="primary" onClick={start} disabled={!draft.enabled}>
            Re-run search pipeline
          </button>
        )}
      </div>

      {!draft.enabled && (
        <div className="notice">
          The agent is switched off. Turn it back on below before running a search.
        </div>
      )}
      {error && <div className="notice error">{error}</div>}

      <div className="knobs">
        <Knob
          label="Smallest award worth applying for"
          hint="Anything below this is never shown to you."
        >
          <input
            type="number"
            step="1000"
            value={draft.min_award}
            onChange={(e) => set("min_award", Number(e.target.value))}
          />
        </Knob>

        <Knob label="Ignore anything due sooner than" hint="Days. Not enough runway otherwise.">
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

        <Knob label="Most to spend on one search" hint="It stops rather than going over.">
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

      <label className="field inline">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => set("enabled", e.target.checked)}
        />
        <span>The agent is switched on</span>
      </label>

      {dirty && (
        <div className="row end">
          <button className="ghost" onClick={() => setDraft(settings)}>
            Undo changes
          </button>
          <button className="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save these settings"}
          </button>
        </div>
      )}

      {/* --- cost and outcome, always visible --- */}
      <div className="runbar">
        <div className="costbar" role="img" aria-label={`${money(spent)} of ${money(ceiling)} spent`}>
          <div
            className="costbar-fill"
            style={{ width: `${Math.min(100, (spent / ceiling) * 100)}%` }}
          />
        </div>
        <div className="muted small">
          Last search cost <strong>${spent.toFixed(4)}</strong> of the ${ceiling.toFixed(2)}{" "}
          limit.
          {run?.stop_reason && ` ${STOP_REASONS[run.stop_reason] || run.stop_reason}`}
          {run?.duplicates_skipped > 0 &&
            ` Skipped ${run.duplicates_skipped} you have already seen this month, for free.`}
        </div>
      </div>

      {(isRunning || live.log?.length > 0) && (
        <div className="runlog">
          <div className="muted small">
            {isRunning ? "Searching…" : "What the last search did"}
          </div>
          <pre ref={logRef}>{(live.log || []).join("\n")}</pre>
        </div>
      )}
    </section>
  );
}
