import { useEffect, useState } from "react";

// Read-only. No accounts, no auth, no settings (CLAUDE.md §3) — config lives in the
// Config tab of the Sheet, which is where Mauri already knows how to edit it.
// This page answers three questions and nothing else: is it on, what has it cost,
// and what happened on each run (§4).

const MONTHLY_CEILING = 20; // §8
const MONTHLY_TARGET = 6;   // §8

function money(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function Stat({ label, value, sub, tone = "" }) {
  return (
    <div className={`stat ${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

function Empty({ title, body }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function CostBar({ spend }) {
  const pct = Math.min(100, (spend / MONTHLY_CEILING) * 100);
  const targetPct = (MONTHLY_TARGET / MONTHLY_CEILING) * 100;
  return (
    <div className="costbar" role="img"
         aria-label={`${money(spend)} spent of a ${money(MONTHLY_CEILING)} ceiling`}>
      <div className="costbar-fill" style={{ width: `${pct}%` }} />
      <div className="costbar-target" style={{ left: `${targetPct}%` }}
           title={`Target: under ${money(MONTHLY_TARGET)}/month`} />
    </div>
  );
}

export default function App() {
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    fetch("/api/runs")
      .then((r) => r.json())
      .then((data) => setState({ status: "ready", data }))
      .catch(() => setState({ status: "error" }));
  }, []);

  if (state.status === "loading") {
    return <div className="page"><p className="muted">Loading…</p></div>;
  }

  if (state.status === "error") {
    return (
      <div className="page">
        <Empty
          title="Couldn't reach the run history"
          body="The page loaded but /api/runs did not respond. If this persists, check the Vercel deployment."
        />
      </div>
    );
  }

  const { configured, reason, error, runs = [], totals = {}, config = {} } = state.data;
  const columns = runs.length ? Object.keys(runs[0]) : [];
  const minAward = config.MIN_AWARD;
  // The agent ships a $25,000 placeholder; §11 Q1 says do not guess at this.
  const awardIsPlaceholder = !minAward || String(minAward).replace(/[^0-9]/g, "") === "25000";

  return (
    <div className="page">
      <header>
        <h1>RISE funding agent</h1>
        <p className="muted">
          Runs Wednesday night. Results wait in the Sheet for Thursday morning.
          This page is read-only — everything is changed in the Sheet.
        </p>
      </header>

      {!configured && (
        <Empty
          title="Not connected to a Sheet yet"
          body={reason || "Add the Sheet id and service-account credentials in Vercel."}
        />
      )}
      {error && <Empty title="Couldn't read the Sheet" body={error} />}

      {configured && !error && (
        <>
          <section className="stats">
            <Stat
              label="Status"
              value={totals.enabled ? "On" : "Off"}
              sub={totals.enabled ? "Runs Wednesday night" : "ENABLED is FALSE in the Sheet"}
              tone={totals.enabled ? "ok" : "off"}
            />
            {/* The timestamp is long enough to wrap onto two lines at the stat's
                default size, so it renders one step smaller. */}
            <Stat label="Last run"
                  value={(totals.lastRun || "never").replace(" UTC", "")}
                  sub={`${totals.runCount || 0} run${totals.runCount === 1 ? "" : "s"} logged${totals.lastRun ? " · UTC" : ""}`}
                  tone="compact" />
            <Stat label="Spent to date" value={money(totals.spendToDate)}
                  sub={`ceiling ${money(MONTHLY_CEILING)}/month`} />
            <Stat
              label="Award floor"
              value={minAward ? `$${Number(String(minAward).replace(/[^0-9]/g, "")).toLocaleString()}` : "unset"}
              sub={awardIsPlaceholder ? "⚠ placeholder — not yet set by Mauri" : "set in the Config tab"}
              tone={awardIsPlaceholder ? "warn" : ""}
            />
          </section>

          <section className="panel">
            <h2>Cost</h2>
            <CostBar spend={totals.spendToDate} />
            <p className="muted small">
              {money(totals.spendToDate)} of a {money(MONTHLY_CEILING)} monthly ceiling.
              The marker is the {money(MONTHLY_TARGET)} target. Each run stops itself at
              $1.00 rather than overspending.
            </p>
          </section>

          <section className="panel">
            <h2>Run history</h2>
            {runs.length === 0 ? (
              <p className="muted">
                No runs logged yet. The Runs tab fills in the first time the agent runs.
              </p>
            ) : (
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {runs.map((run, i) => (
                      <tr key={i}>
                        {columns.map((c) => (
                          <td key={c} className={c === "Notes" ? "notes" : ""}>
                            {run[c]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <footer className="muted small">
        Built at the AI Trailblazers Social Impact Hack-AI-thon, San Diego, Aug 2026.
        RISE San Diego owns this work. To change what the agent looks for, or to stop
        it, edit the Config tab of the Sheet — not this page.
      </footer>
    </div>
  );
}
