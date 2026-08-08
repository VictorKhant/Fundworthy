import { useEffect, useRef } from "react";
import Icon, { IconButton } from "./Icon";

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
//
// The options are **radios**. They were pressed-state buttons carrying an "In use" chip,
// which put a third badge on a row that already had "Recommended" and a price — three
// marks, one of which was silently the selection state. A radio is the one control
// everybody already reads as "this is the one that is on".

const BLURB = {
  2: "This step asks one yes/no question of every page that survived the free filters, "
   + "so it runs the most times and the cheap answer is usually the right one.",
  3: "This step reads the whole page and writes the score you act on. It runs on the "
   + "fewest pages and it is the judgement you are paying for.",
};

export default function ModelPicker({
  stage, choices, current, lastCost, effortChoices = [], currentEffort = "",
  onClose, onPick, onPickEffort,
}) {
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

  // `preventScroll`, because the dialog scrolls internally and focusing the first option
  // scrolled the sentence explaining the step up under the sticky header — so the panel
  // opened already having hidden the thing it opens to say.
  useEffect(() => {
    if (stage) panel.current?.querySelector(".modelopt")?.focus({ preventScroll: true });
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
          <span className={`stage-badge big n${stage.n}`} aria-hidden="true">{stage.n}</span>
          <span className="picker-heading">
            Which model does {stage.title.toLowerCase()}?
            <small>You can change this before any search.</small>
          </span>
          <IconButton name="close" label="Close" className="dialog-x" onClick={close} />
        </h2>

        <p className="dialog-body">{BLURB[stage.n]}</p>

        <ul className="modellist" role="radiogroup" aria-labelledby="picker-title">
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
                  role="radio"
                  className={`modelopt ${mine ? "on" : ""}`}
                  onClick={() => (mine ? close() : onPick(c.id))}
                  aria-checked={mine}
                >
                  <span className="modelopt-radio" aria-hidden="true" />
                  <span className="modelopt-body">
                    <span className="modelopt-head">
                      <span className="modelopt-name">{c.label}</span>
                      {c.recommended && <span className="chip">Recommended</span>}
                      {projected != null && (
                        <span className="modelopt-cost">
                          ~${projected.toFixed(4)}
                        </span>
                      )}
                    </span>
                    <span className="modelopt-note">{c.note}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {/* How hard the chosen model thinks before it answers — a separate dial from
            *which* model runs the step. Haiku cannot take an effort level at all (a
            live 400, not a preference), so rather than offer a control that would
            break the very next search, the section explains why it is missing
            instead of rendering broken radios. */}
        {current && current.includes("haiku") ? (
          <p className="muted small modelpicker-effort-note">
            Haiku does not support a reasoning-depth setting — pick Sonnet or Opus
            above to unlock it.
          </p>
        ) : effortChoices.length > 0 && (
          <div className="modelpicker-effort">
            <h3 className="modelpicker-effort-heading">How hard should it think?</h3>
            <ul className="modellist modellist-compact" role="radiogroup"
                aria-label="Reasoning effort">
              {effortChoices.map((c) => {
                const mine = c.id === (currentEffort || "");
                return (
                  <li key={c.id || "default"}>
                    <button
                      type="button"
                      role="radio"
                      className={`modelopt ${mine ? "on" : ""}`}
                      onClick={() => !mine && onPickEffort?.(c.id)}
                      aria-checked={mine}
                    >
                      <span className="modelopt-radio" aria-hidden="true" />
                      <span className="modelopt-body">
                        <span className="modelopt-head">
                          <span className="modelopt-name">{c.label}</span>
                        </span>
                        <span className="modelopt-note">{c.note}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* Where the other providers come from. It points at a panel that exists and
            currently has one live provider on it — which is the point: the line is not a
            promise, it is a route to the place the answer will be. */}
        {/* The text is wrapped in a span deliberately. This is a flex row, and a bare
            text node beside an element becomes its own anonymous flex ITEM — so the
            sentence, the <strong> and the tail laid themselves out as three narrow
            columns rather than one line. */}
        <p className="muted small modelpicker-more">
          <Icon name="add" size={13} />
          <span>
            Add OpenAI, DeepSeek or Qwen under{" "}
            <strong>Settings → Which AI it uses</strong> and their models appear here too.
          </span>
        </p>

        <p className="muted small">
          {lastCost > 0
            ? "Costs are what this step would have cost on your last search. A longer "
              + "funder list costs more."
            : "Costs appear here once you have run a search."}{" "}
          Whatever you pick, a search still stops itself at your per-search limit.
        </p>
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
  // Opus 5 is $5/$25 per Mtok against Sonnet's $3/$15 — a consistent ~1.67x on both
  // input and output, not the ~5x the old (now-retired) claude-opus-4-1 was.
  "anthropic:claude-opus-5": 10.0,
};
