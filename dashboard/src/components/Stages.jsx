import { useState } from "react";
import { api } from "../api";
import Icon from "./Icon";
import ModelPicker from "./ModelPicker";
import StageDetail from "./StageDetail";

// What the search actually did, as three boxes — one per tier of CLAUDE.md §5.
//
// This replaces a streaming log as the *primary* account of a run. The log is still
// there (behind the disclosure this section's header opens) and is still the only thing
// that explains a run that died halfway, but as a summary it was useless to the person
// this is built for: it says `rejected [award_below_floor] Micro Grants — $4,000 <
// $10,000` and assumes you know what a tier is.
//
// The boxes answer the question somebody actually has after a thin week, which is not
// "what did the pipeline do" but **"why so few?"** — and the honest answer is almost
// always "most of your funders' pages were filtered out for free, here they are".
//
// The visual order is the cost order, and it is the argument: free, cheap, expensive.
//
// **They stay mounted while a run is going, and show it.** They used to be hidden for
// the whole of a search and appear at the end holding finished numbers — which made the
// one thing somebody watches for five to ten minutes the one thing they could not see.
// The old comment reasoned that last week's funnel above a live log would read as this
// run's progress; that was the right problem and the wrong fix. The fix is to make the
// boxes *be* the progress, which is the entire reason they were asked for.

const STAGES = [
  {
    n: 1,
    key: "free",
    title: "Free filters",
    engine: "Plain rules",
    // What the big number IS. It used to render "23 of 61" at one size, which makes a
    // funnel of three cards unreadable at a glance — the eye has nothing to compare.
    // The pass count alone is the number; the denominator drops to the footer.
    label: "pages worth paying to read",
    foot: (n) => `of ${n} checked · free`,
  },
  {
    n: 2,
    key: "triage",
    title: "Quick read",
    engine: "Haiku",
    label: "worth full scoring",
    foot: (n) => `of ${n} read`,
  },
  {
    n: 3,
    key: "score",
    title: "Full scoring",
    engine: "Sonnet",
    label: "on your list this week",
    foot: (n) => `of ${n} scored`,
  },
];

export default function Stages({
  run, isRunning, cap = 6, settings = {}, choices = {}, defaults = {},
  effortChoices = [], logOpen, onToggleLog, onChange,
}) {
  const [open, setOpen] = useState(null);
  const [picking, setPicking] = useState(null);
  if (!run) return null;

  const chosen = {
    2: settings.triage_model || defaults["2"],
    3: settings.scoring_model || defaults["3"],
  };
  const chosenEffort = {
    2: settings.triage_effort || "",
    3: settings.scoring_effort || "",
  };
  const labelFor = (n) =>
    (choices[n] || []).find((c) => c.id === chosen[n])?.label
    || (chosen[n] || "").split(":").pop();

  const cost = run.usd_by_stage || {};

  // The two denominators, written into `progress.funnel` by the runner while the search
  // is going and gone by the time it ends — `_finalize` replaces `progress` with the
  // outcome. So a finished run falls back to the columns, which is what it has always
  // read, and only a live one gets the extra pair.
  const funnel = (isRunning && run.progress?.funnel) || null;

  const parsed = run.candidates_parsed || 0;
  const triaged = run.triaged || 0;
  const scored = run.scored || 0;
  // Deliberately `survivors` and not `triaged` for stage 1's pass count. They are equal
  // on a run that read everything, and they are not on a run that stopped at the result
  // cap — where "how many pages were worth paying to read" is the survivor count and
  // "how many did we get round to" is the triaged one. Stage 1's label says the former.
  // Live funnel first, then the persisted column (v16), then `triaged` for rows written
  // before that column existed. The fallback used to be `triaged` alone, which is only
  // the same number on a run that read everything — so a run the consecutive-error
  // breaker stopped after 5 reported "5 went through" of 344 when the free filters had
  // passed far more and we simply never got to them. `|| triaged` and not `?? triaged`
  // on purpose: an old row reads back 0 from the DEFAULT, not null.
  const survived = funnel?.survivors ?? (run.survivors || triaged);
  const kept = funnel?.kept
    ?? ((run.opportunities_scored || 0) + (run.opportunities_not_stated || 0));

  // came in / went through, per stage. Each stage's intake is the one before it, which
  // is what makes the row of boxes readable left to right as one funnel.
  const flow = {
    1: { came: parsed, through: survived },
    2: { came: survived, through: scored },
    3: { came: scored, through: kept },
  };

  // Which box is working. The furthest one that has been reached, never the one that
  // happens to be executing this millisecond: triage and scoring interleave candidate by
  // candidate inside one loop, so "whichever just ran" would strobe between two cards
  // several times a second. The stages behind it keep their bars moving, which is the
  // honest signal that they are not finished either.
  const at = !isRunning ? 0 : scored > 0 ? 3 : funnel?.survivors != null ? 2 : 1;

  // How full each bar is, and every one of them is a real fraction of a real total
  // rather than a number invented to make something move:
  //   1  unknowable mid-crawl — nothing knows how many pages a funder list will yield
  //      until it has been fetched, so this one is an indeterminate sweep and says so
  //   2  of the pages that survived the free filters, how many have been read
  //   3  of the results you asked for, how many are found  (the `target_met` condition)
  const rail = {
    1: funnel?.survivors != null ? 1 : null,
    2: survived > 0 ? Math.min(1, triaged / survived) : 0,
    3: cap > 0 ? Math.min(1, kept / cap) : 0,
  };

  return (
    <section className="stagework" aria-label="What the search did">
      {/* The grid had no heading at all, and the log was a separate disclosure further
          down the page with no relationship to it. One row states what the three boxes
          are, and hands the log the only job it still has. */}
      <div className="stagework-head">
        <h2 className="stagework-title">How this week's list was made</h2>
        {onToggleLog && (
          <button className="text stagework-log" onClick={onToggleLog}
                  aria-expanded={Boolean(logOpen)}>
            <Icon name="terminal" size={14} />
            {logOpen ? "Hide the technical log" : "Show the technical log"}
          </button>
        )}
      </div>

      <div className="stages">
        {STAGES.map((s, i) => {
          const { came, through } = flow[s.n];
          const spent = cost[String(s.n)] ?? 0;
          const state = !isRunning ? "" : at === s.n ? "at" : at > s.n ? "done" : "waiting";
          return (
            <div key={s.key} className={`stagecell ${state}`}>
              {/* The connector lives in the grid gap, so it belongs to the cell on its
                  right rather than sitting between two of them as a third element that
                  would take a column of its own. */}
              {i > 0 && (
                <span className="stage-link" aria-hidden="true">
                  <span className="stage-link-rule" />
                  {isRunning && at === s.n && <span className="stage-link-dot" />}
                </span>
              )}

              <div
                role="button"
                tabIndex={0}
                className={`stage stage-${s.key}`}
                onClick={() => setOpen(s)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(s); }
                }}
                aria-label={`${s.title} — ${through} of ${came} went through. Open the detail.`}
              >
                <span className="stage-head">
                  <span className="stage-badge" aria-hidden="true">{s.n}</span>
                  <span className="stage-title">{s.title}</span>
                  <span className="stage-dot" aria-hidden="true" />
                </span>

                <span className="stage-count">{through}</span>
                <span className="stage-label">{s.label}</span>

                <span className="stage-rule" aria-hidden="true" />

                <span className="stage-foot">
                  <span className="stage-of">{s.foot(came)}</span>
                  {/* The card was clickable and nothing said so. */}
                  <span className="stage-why">Why ›</span>
                </span>

                {/* Only while something is happening. A finished run's bars would be
                    three full rails saying nothing. */}
                {isRunning && (
                  <span className={`stage-rail ${rail[s.n] == null ? "sweep" : ""}`}
                        aria-hidden="true">
                    <span
                      className="stage-rail-fill"
                      style={rail[s.n] == null
                        ? undefined
                        : { width: `${Math.round(rail[s.n] * 100)}%` }}
                    />
                  </span>
                )}
              </div>

              {/* Out of the card and under it, so all three engine rows line up on one
                  baseline whatever the cards above them do. The per-stage cost is NOT
                  here: four decimal places across a row of three cards reads as noise,
                  and the number people want on a card is the count. It is in the stage
                  detail's figures instead. */}
              <button
                type="button"
                className={`stage-engine ${s.n === 1 ? "fixed" : ""}`}
                onClick={s.n === 1 ? undefined : () => setPicking(s)}
                disabled={s.n === 1}
                title={s.n === 1
                  ? "This step is plain rules — there is no model to choose"
                  : `Change which model does ${s.title.toLowerCase()}`}
              >
                <span className="stage-engine-label">Engine</span>
                <span className="stage-engine-value">
                  {s.n === 1 ? s.engine : labelFor(s.n)}
                </span>
                {s.n !== 1 && (
                  <span className="stage-engine-caret" aria-hidden="true">
                    <Icon name="chevron" size={13} />
                  </span>
                )}
              </button>
            </div>
          );
        })}
      </div>

      <ModelPicker
        stage={picking}
        choices={choices[picking?.n] || []}
        current={picking ? chosen[picking.n] : null}
        // Rough, and labelled as rough. The honest number is what the last run cost;
        // scaling it by the price ratio is the only forecast available before a run and
        // is far more use than no number at all when Opus costs more than Sonnet.
        lastCost={picking ? (cost[String(picking.n)] ?? 0) : 0}
        effortChoices={effortChoices}
        currentEffort={picking ? chosenEffort[picking.n] : ""}
        onClose={() => setPicking(null)}
        onPick={async (id) => {
          const n = picking.n;
          setPicking(null);
          await api.settings.save(n === 2 ? { triage_model: id } : { scoring_model: id });
          await onChange?.();
        }}
        onPickEffort={async (id) => {
          const n = picking.n;
          await api.settings.save(
            n === 2 ? { triage_effort: id } : { scoring_effort: id });
          await onChange?.();
        }}
      />

      <StageDetail
        stage={open}
        run={run}
        flow={open ? flow[open.n] : null}
        cost={open ? (open.n === 1 ? 0 : cost[String(open.n)] ?? 0) : 0}
        // Their floor, not the default. Stage 1's pass rule names a figure, and naming
        // $10,000 to an org that set theirs to $25,000 would be the one kind of wrong
        // that panel exists to prevent.
        floor={settings.min_award ?? 10000}
        onClose={() => setOpen(null)}
      />
    </section>
  );
}
