import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import Spinner from "./Spinner";

// What one step of the search did, opened from its box.
//
// The shape is: the four numbers, one plain paragraph, then the reasons — and **each
// reason expands to the funders it set aside**, with the specific detail for each page.
// That last part is the whole feature. "12 rejected below your award floor" is a
// statistic; "Micro Grants — $4,000 < $10,000" is something you can disagree with, and
// disagreeing with it is how somebody discovers their floor is set wrong.
//
// The rows come from their own endpoint on open rather than riding along with the
// dashboard, because there can be hundreds and almost nobody looks.

// Plain-language names for the machine keys the pipeline emits. A reason with no entry
// here falls back to its key with the underscores taken out — ugly, but never blank, and
// a new reject reason shipping without a label should look unfinished rather than
// invisible.
const REASON_LABEL = {
  award_below_floor: "The award was below your floor",
  deadline_too_soon: "The deadline was too close",
  deadline_passed: "The deadline had already passed",
  on_the_remove_list: "You had taken this funder off the search",
  already_seen_this_month: "Already on this month's list",
  thin_landing_page: "The page had almost nothing on it",
  triage_not_an_opportunity: "Not an open funding opportunity",
  claim_could_not_be_confirmed: "Kept, but a claim could not be confirmed",
  no_award_stated: "No award amount anywhere on the page",
};

const label = (reason) =>
  REASON_LABEL[reason] || reason.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

const PARAGRAPH = {
  1: "These pages were fetched and checked without any AI, so this step is free however "
   + "much it throws away. Anything set aside here never cost you a penny — and if a "
   + "rejection below looks wrong, the fix is usually your award floor or your deadline "
   + "runway under “Adjust search settings”.",
  2: "Each surviving page got one cheap question, and the answer below is the "
   + "researcher's own words. This step exists so the expensive one only reads pages "
   + "that are genuinely open calls.",
  3: "These were read in full and scored. Anything set aside here was already past both "
   + "cheaper checks, so it is usually a deadline the parser could not see earlier.",
};

export default function StageDetail({ stage, run, flow, cost, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [showAll, setShowAll] = useState({});
  const panel = useRef(null);
  const returnTo = useRef(null);

  const runId = run?.id;

  const load = useCallback(async () => {
    if (!runId) return;
    try {
      setData(await api.runs.rejects(runId, { limit: 400 }));
    } catch (e) {
      setError(e.message);
    }
  }, [runId]);

  useEffect(() => {
    if (!stage) return;
    returnTo.current = document.activeElement;
    setData(null);
    setError(null);
    setExpanded(null);
    setShowAll({});
    load();
  }, [stage, load]);

  useEffect(() => {
    if (!stage) return undefined;
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  if (!stage) return null;

  function close() {
    onClose();
    returnTo.current?.focus?.();
  }

  const groups = (data?.groups || []).filter((g) => g.stage === stage.n);
  const rows = data?.rejects || [];
  const setAside = Math.max((flow?.came || 0) - (flow?.through || 0), 0);

  return (
    <div className="dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog stagedetail" role="dialog" aria-modal="true"
           aria-labelledby="stage-title" ref={panel}>
        <h2 id="stage-title">{stage.title}</h2>

        <div className="stage-figures">
          <span><strong>{flow?.came ?? 0}</strong> came in</span>
          <span><strong>{flow?.through ?? 0}</strong> went through</span>
          <span><strong>{setAside}</strong> set aside</span>
          <span><strong>{stage.n === 1 ? "$0.00" : `$${(cost || 0).toFixed(4)}`}</strong> spent</span>
        </div>

        <p className="dialog-body">{PARAGRAPH[stage.n]}</p>

        {error && <div className="notice error">{error}</div>}
        {!data && !error && (
          <p className="loading-line">
            <Spinner label="Loading what this step set aside" />
            Loading…
          </p>
        )}

        {data && groups.length === 0 && (
          <p className="muted small">
            Nothing was set aside at this step.
          </p>
        )}

        {data?.truncated && (
          <p className="muted small">
            This search set aside a great many pages. The counts below are complete; the
            lists under them show the first few hundred.
          </p>
        )}

        <ul className="reasonlist">
          {groups.map((g) => {
            const mine = rows.filter((r) => r.reason === g.reason);
            const isOpen = expanded === g.reason;
            const visible = showAll[g.reason] ? mine : mine.slice(0, 5);
            return (
              <li key={g.reason} className="reason">
                <button
                  type="button"
                  className="reason-head"
                  onClick={() => setExpanded(isOpen ? null : g.reason)}
                  aria-expanded={isOpen}
                >
                  <span className="reason-caret" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                  <span className="reason-name">{label(g.reason)}</span>
                  <span className="reason-count">{g.total}</span>
                </button>

                {isOpen && (
                  g.rows === 0 ? (
                    // The indexed databases aggregate their own rejects before we see
                    // them, so there is a count and no rows. Say that, rather than
                    // showing an empty drawer that looks broken.
                    <p className="muted small reason-none">
                      These came from a public grants database, which filters before we
                      read anything — so there is a count but no page-by-page detail.
                    </p>
                  ) : (
                    <>
                      <ul className="rejectlist">
                        {visible.map((r, i) => (
                          <li key={`${r.url}-${i}`}>
                            <span className="reject-funder">{r.funder}</span>
                            {r.url ? (
                              <a href={r.url} target="_blank" rel="noopener noreferrer">
                                {r.title || r.url}
                              </a>
                            ) : (
                              <span>{r.title}</span>
                            )}
                            {r.detail && <span className="reject-detail">{r.detail}</span>}
                          </li>
                        ))}
                      </ul>
                      {mine.length > visible.length && (
                        <button
                          className="text small"
                          onClick={() => setShowAll({ ...showAll, [g.reason]: true })}
                        >
                          Show the other {mine.length - visible.length}
                        </button>
                      )}
                    </>
                  )
                )}
              </li>
            );
          })}
        </ul>

        <div className="dialog-actions">
          <button className="primary" onClick={close} autoFocus>Close</button>
        </div>
      </div>
    </div>
  );
}
