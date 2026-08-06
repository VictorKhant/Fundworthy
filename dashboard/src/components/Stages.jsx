import { useState } from "react";
import { api } from "../api";
import ModelPicker from "./ModelPicker";
import StageDetail from "./StageDetail";

// What the search actually did, as three boxes — one per tier of CLAUDE.md §5.
//
// This replaces a streaming log as the *primary* account of a run. The log is still
// there (behind a disclosure on the dashboard) and is still the only thing that explains
// a run that died halfway, but as a summary it was useless to the person this is built
// for: it says `rejected [award_below_floor] Micro Grants — $4,000 < $10,000` and
// assumes you know what a tier is.
//
// The boxes answer the question somebody actually has after a thin week, which is not
// "what did the pipeline do" but **"why so few?"** — and the honest answer is almost
// always "most of your funders' pages were filtered out for free, here they are".
//
// The visual order is the cost order, and it is the argument: free, cheap, expensive.
// Tier 1 shows $0.00 rather than nothing, because "the free tier is free" is the whole
// cost strategy and an empty cost line next to two populated ones reads as missing data.

const STAGES = [
  {
    n: 1,
    key: "free",
    title: "Read and filtered",
    engine: "Plain rules",
    blurb: "Every page on your funder list, fetched and checked against your award "
         + "floor, your deadline runway and your remove list. No AI, no cost.",
  },
  {
    n: 2,
    key: "triage",
    title: "Quick look",
    engine: "Haiku",
    blurb: "Whatever survived gets one cheap question: is this an open funding "
         + "opportunity you could actually apply for?",
  },
  {
    n: 3,
    key: "score",
    title: "Read properly",
    engine: "Sonnet",
    blurb: "The survivors are read in full and scored on fit, award size and whether "
         + "the application can be finished in time.",
  },
];

export default function Stages({ run, settings = {}, choices = {}, defaults = {}, onChange }) {
  const [open, setOpen] = useState(null);
  const [picking, setPicking] = useState(null);
  if (!run) return null;

  const chosen = {
    2: settings.triage_model || defaults["2"],
    3: settings.scoring_model || defaults["3"],
  };
  const labelFor = (n) =>
    (choices[n] || []).find((c) => c.id === chosen[n])?.label
    || (chosen[n] || "").split(":").pop();

  const cost = run.usd_by_stage || {};
  const parsed = run.candidates_parsed || 0;
  const triaged = run.triaged || 0;
  const scored = run.scored || 0;
  const kept = (run.opportunities_scored || 0) + (run.opportunities_not_stated || 0);

  // came in / went through, per stage. Each stage's intake is the one before it, which
  // is what makes the row of boxes readable left to right as one funnel.
  const flow = {
    1: { came: parsed, through: triaged },
    2: { came: triaged, through: scored },
    3: { came: scored, through: kept },
  };

  return (
    <section className="stages" aria-label="What the search did">
      {STAGES.map((s) => {
        const { came, through } = flow[s.n];
        const setAside = Math.max(came - through, 0);
        const spent = cost[String(s.n)] ?? 0;
        return (
          <div
            key={s.key}
            role="button"
            tabIndex={0}
            className={`stage stage-${s.key}`}
            onClick={() => setOpen(s)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(s); }
            }}
            aria-label={`${s.title} — ${through} of ${came} went through. Open the detail.`}
          >
            <span className="stage-n">Step {s.n}</span>
            <span className="stage-title">{s.title}</span>

            <span className="stage-count">
              <strong>{through}</strong>
              <span className="muted"> of {came}</span>
            </span>
            <span className="stage-foot">
              {setAside > 0
                ? `${setAside} set aside`
                : came === 0 ? "nothing reached this step" : "all went through"}
            </span>

            {/* The engine row is a nested control, so the box itself cannot be a
                <button> — a button inside a button is invalid and React will not
                render it. The card is a div with a role instead, and the picker stops
                the click from opening the detail behind it. */}
            <span className="stage-engine">
              <span className="muted">Engine</span>
              {s.n === 1 ? (
                <span className="muted">{s.engine}</span>
              ) : (
                <button
                  type="button"
                  className="text stage-model"
                  onClick={(e) => { e.stopPropagation(); setPicking(s.n); }}
                  title={`Change which model does step ${s.n}`}
                >
                  {labelFor(s.n)}
                </button>
              )}
              <span className="stage-cost">
                {s.n === 1 ? "$0.00" : `$${spent.toFixed(4)}`}
              </span>
            </span>
          </div>
        );
      })}

      <ModelPicker
        stage={picking}
        choices={choices[picking] || []}
        current={picking ? chosen[picking] : null}
        // Rough, and labelled as rough. The honest number is what the last run cost;
        // scaling it by the price ratio is the only forecast available before a run and
        // is far more use than no number at all when Opus is five times Sonnet.
        lastCost={picking ? (cost[String(picking)] ?? 0) : 0}
        onClose={() => setPicking(null)}
        onPick={async (id) => {
          await api.settings.save(
            picking === 2 ? { triage_model: id } : { scoring_model: id });
          setPicking(null);
          await onChange?.();
        }}
      />

      <StageDetail
        stage={open}
        run={run}
        flow={open ? flow[open.n] : null}
        cost={open ? (open.n === 1 ? 0 : cost[String(open.n)] ?? 0) : 0}
        onClose={() => setOpen(null)}
      />
    </section>
  );
}
