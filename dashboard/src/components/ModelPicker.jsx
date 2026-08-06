import { useEffect, useRef } from "react";

// Which model does one step of the search, opened from that step's Engine row.
//
// Deliberately **not** inside the stage-detail modal. That panel is an account of what
// happened; this changes what happens next, and mixing "here is what your search did"
// with "here is a control that changes your bill" makes both harder to read.
//
// The projected cost is the reason this is a dialog and not a dropdown. Opus is five
// times Sonnet's price, and on a long funder list picking it means the run hits the
// per-search limit partway down the list and stops — which looks like a broken search
// rather than a choice somebody made. So the number is on the option, before the click.
//
// It is a **projection from the last run**, and it says so. There is no honest forecast
// before a search has ever run, and inventing one would be a number under a spending
// limit that nothing stands behind.

export default function ModelPicker({ stage, choices, current, lastCost, onClose, onPick }) {
  const panel = useRef(null);
  const returnTo = useRef(null);

  useEffect(() => {
    if (!stage) return undefined;
    returnTo.current = document.activeElement;
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    if (stage) panel.current?.querySelector("button")?.focus();
  }, [stage]);

  if (!stage) return null;

  function close() {
    onClose();
    returnTo.current?.focus?.();
  }

  // The price ratio between two models, so "what would this have cost instead" is
  // answerable from the run that just happened.
  const rate = (id) => RATES[id] ?? null;
  const currentRate = rate(current);

  return (
    <div className="dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog modelpicker" role="dialog" aria-modal="true"
           aria-labelledby="picker-title" ref={panel}>
        <h2 id="picker-title">
          {stage === 2 ? "Which model takes the quick look?" : "Which model reads properly?"}
        </h2>
        <p className="dialog-body">
          {stage === 2
            ? "This step asks one yes/no question of every page that survived the free "
              + "filters, so it runs the most times and the cheap answer is usually the "
              + "right one."
            : "This step reads the whole page and writes the score you act on. It runs "
              + "on the fewest pages and it is the judgement you are paying for."}
        </p>

        <ul className="modellist">
          {choices.map((c) => {
            const mine = c.id === current;
            const r = rate(c.id);
            const projected = (lastCost > 0 && r && currentRate)
              ? lastCost * (r / currentRate)
              : null;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  className={`modelopt ${mine ? "on" : ""}`}
                  onClick={() => (mine ? close() : onPick(c.id))}
                  aria-pressed={mine}
                >
                  <span className="modelopt-head">
                    <span className="modelopt-name">{c.label}</span>
                    {c.recommended && <span className="chip">Recommended</span>}
                    {mine && <span className="chip strong">In use</span>}
                    {projected != null && (
                      <span className="modelopt-cost">
                        ~${projected.toFixed(4)}
                      </span>
                    )}
                  </span>
                  <span className="modelopt-note">{c.note}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <p className="muted small">
          {lastCost > 0
            ? "Costs are what this step would have cost on your last search. A longer "
              + "funder list costs more."
            : "Costs appear here once you have run a search."}{" "}
          Whatever you pick, a search still stops itself at your per-search limit.
        </p>

        <div className="dialog-actions">
          <button className="text" onClick={close}>Close</button>
        </div>
      </div>
    </div>
  );
}

// Blended $/Mtok, only ever used as a RATIO between two options — so it does not have to
// match a real input/output mix, it has to be proportional. Kept here rather than
// fetched because it is presentation: the authoritative table is PRICING in
// agent/score.py, and that is what actually meters the spend.
const RATES = {
  "anthropic:claude-haiku-4-5": 2.0,
  "anthropic:claude-sonnet-4-6": 6.0,
  "anthropic:claude-opus-4-1": 30.0,
};
