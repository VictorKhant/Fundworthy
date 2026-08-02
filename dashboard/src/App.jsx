import { useEffect, useState } from "react";

// Read-only results view. The agent commits dashboard/public/run.json each run
// (agent/run.py --sink web); this page loads that file directly — no backend, no Google
// credential in the browser, the Sheet stays private. Mauri reviews the results here,
// then (next build step) prunes and exports the ones she keeps to her own Google Sheet
// via Gmail. Replaces the earlier serverless /api/runs reader (decision A6 Opt 2).

const RUN_CEILING = 1.0; // §8 per-run hard ceiling

function money(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function fmtMoney(n) {
  return n == null ? null : `$${Number(n).toLocaleString()}`;
}

function awardRange(o) {
  const lo = fmtMoney(o.award_min);
  const hi = fmtMoney(o.award_max);
  if (lo && hi) return lo === hi ? hi : `${lo}–${hi}`;
  return hi || lo || null;
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

function CostBar({ spend, ceiling }) {
  const pct = Math.min(100, (spend / ceiling) * 100);
  return (
    <div
      className="costbar"
      role="img"
      aria-label={`${money(spend)} spent of a ${money(ceiling)} per-run ceiling`}
    >
      <div className="costbar-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

function Opp({ o }) {
  const range = awardRange(o);
  return (
    <article className="opp">
      <div className="opp-score" title="Score 0–100">
        {o.section === "scored" ? o.score : "—"}
      </div>
      <div className="opp-body">
        <div className="opp-head">
          <span className="opp-funder">{o.funder}</span>
          {o.needs_human_check && <span className="badge warn">needs a human check</span>}
        </div>
        <div className="opp-title">{o.title}</div>
        {o.score_rationale && <div className="opp-why">{o.score_rationale}</div>}
        <div className="opp-meta">
          {range && (
            <span>
              <strong>{range}</strong>
            </span>
          )}
          {o.deadline && (
            <span>
              due {o.deadline}
              {o.days_left != null ? ` · ${o.days_left}d left` : ""}
            </span>
          )}
          {o.estimated_effort_hours != null && <span>~{o.estimated_effort_hours}h</span>}
          {o.program_match?.length > 0 && <span>{o.program_match.join(", ")}</span>}
          <a href={o.source_url} target="_blank" rel="noopener noreferrer">
            view source ↗
          </a>
        </div>
      </div>
    </article>
  );
}

export default function App() {
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    fetch("/run.json", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("no run.json");
        return r.json();
      })
      .then((data) => setState({ status: "ready", data }))
      .catch(() => setState({ status: "empty" }));
  }, []);

  if (state.status === "loading") {
    return (
      <div className="page">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (state.status === "empty") {
    return (
      <div className="page">
        <header>
          <h1>RISE funding finder</h1>
        </header>
        <Empty
          title="No results yet"
          body="Run the agent (python -m agent.run --sink web) to generate this week's opportunities."
        />
      </div>
    );
  }

  const { generated_at, run = {}, scored = [], amount_not_stated = [] } = state.data;
  const when = (generated_at || run.started_at || "")
    .replace("T", " ")
    .replace(/\..*/, " UTC");

  return (
    <div className="page">
      <header>
        <h1>RISE funding finder</h1>
        <p className="muted">
          This week's opportunities, every one above the award floor. Review them, keep
          the ones worth 10 hours, and export those to your Google Sheet.
        </p>
      </header>

      <section className="stats">
        <Stat
          label="Worth a look"
          value={scored.length}
          sub={`+ ${amount_not_stated.length} with no amount stated`}
        />
        <Stat
          label="This run"
          value={money(run.usd_spent)}
          sub={`ceiling ${money(RUN_CEILING)} · ${run.stop_reason || "—"}`}
        />
        <Stat
          label="Sources checked"
          value={run.sources_ok ?? "—"}
          sub={`${run.candidates_parsed ?? 0} pages read`}
          tone="compact"
        />
        <Stat label="Generated" value={when || "—"} tone="compact" />
      </section>

      <section className="panel">
        <h2>Cost — this run</h2>
        <CostBar spend={run.usd_spent || 0} ceiling={RUN_CEILING} />
        <p className="muted small">
          {money(run.usd_spent)} of the {money(RUN_CEILING)} per-run ceiling. The run
          stops itself rather than overspending.
        </p>
      </section>

      <section className="panel">
        <h2>Above the floor — ranked</h2>
        {scored.length === 0 ? (
          <p className="muted">
            Nothing cleared the floor this run. That can be a good week.
          </p>
        ) : (
          <div className="opps">
            {scored.map((o) => (
              <Opp key={o.id} o={o} />
            ))}
          </div>
        )}
      </section>

      {amount_not_stated.length > 0 && (
        <section className="panel">
          <h2>Amount not stated — needs a human look</h2>
          <p className="muted small">
            The funder's page didn't state an award amount, so these aren't ranked. Open
            each to check — we never guess a number.
          </p>
          <div className="opps">
            {amount_not_stated.map((o) => (
              <Opp key={o.id} o={o} />
            ))}
          </div>
        </section>
      )}

      <section className="panel muted small">
        <strong>Next:</strong> select which to keep and export them to your connected
        Google Sheet. (Pruning + Gmail export are the next build step.)
      </section>

      <footer className="muted small">
        Built at the AI Trailblazers Social Impact Hack-AI-thon, San Diego, Aug 2026.
        RISE San Diego owns this work.
      </footer>
    </div>
  );
}
