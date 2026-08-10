import { useCallback, useEffect, useRef, useState } from "react";
import { api, money } from "../api";
import Icon, { IconButton } from "./Icon";
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
  // Two funders linking the same grant, or a redirect landing somewhere already read.
  // Not the same as the line above, which is the monthly archive dedup.
  already_seen_this_run: "The same page came up twice in this search",
  thin_landing_page: "The page had almost nothing on it",
  triage_not_an_opportunity: "Not an open funding opportunity",
  // A real, open, sometimes well-funded call — just not for anything this
  // organization does. Split out from the reason above so a closed program and a
  // $750K grant for the wrong kind of work stop reading as the same failure.
  triage_wrong_topic: "Open, but not something you do",
  claim_could_not_be_confirmed: "Kept, but a claim could not be confirmed",
  no_award_stated: "No award amount anywhere on the page",
  // Not a verdict about the page — a failure of ours. These two used to be invisible:
  // the count went nowhere and the exception went to a log line and one run note that
  // nothing renders, so a search whose every model call failed showed an empty
  // "nothing was set aside" panel. Each row now carries the actual error as its detail.
  triage_error: "Could not be read — the quick read failed",
  scoring_error: "Could not be scored — the full read failed",
};

const label = (reason) =>
  REASON_LABEL[reason] || reason.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

// Why the ones that got through, got through. The panel only ever had the second half —
// the reasons things were set aside — which quietly makes a rejection log out of a page
// that is supposed to explain a step. A person looking at "23 of 61" wants both halves,
// and the pass rule is the one that tells them whether their own settings are doing what
// they meant. Every sentence here is the free-tier filter list, the triage question and
// the scoring threshold stated in the words they are actually implemented in.
// The floor is theirs, not the default. Every other sentence here is fixed, but an org
// that set its floor to $25,000 being told its own filter is $10,000 would be the one
// kind of wrong this panel exists to prevent.
const PASSED = (floor) => ({
  1: `Every one of these named a grant, was open, was over your ${money(floor)} floor, `
   + "and had enough runway to write an application.",
  2: "The model found language matching one of your ticked programs on the page itself.",
  3: "Scored 55 or better on award size, program fit, effort and deadline runway — and "
   + "every stated figure was found word-for-word on the funder's page.",
});

const PARAGRAPH = {
  1: "These pages were fetched and checked without any AI, so this step is free however "
   + "much it throws away. Anything set aside here never cost you a penny — and if a "
   + "rejection below looks wrong, the fix is usually your award floor or your deadline "
   + "runway under “Adjust search settings”.",
  2: "Each surviving page got two cheap questions — is it a real, open call, and does "
   + "it match what you actually do — and the answer below is the researcher's own "
   + "words. This step exists so the expensive one only reads pages that are "
   + "genuinely worth a closer look.",
  3: "These were read in full and scored. Anything set aside here was already past both "
   + "cheaper checks, so it is usually a deadline the parser could not see earlier.",
};

export default function StageDetail({ stage, run, flow, cost, floor = 10000, onClose }) {
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
    // The ✕ is the only way out other than Esc now that the footer Close is gone, so
    // focus has to land on it — otherwise a keyboard user opens this and is left in the
    // document behind it.
    panel.current?.querySelector(".dialog-x")?.focus({ preventScroll: true });
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
  // What the longest bar is measured against. Proportional to the biggest reason rather
  // than to the total, because a run where one reason accounts for 90% would otherwise
  // render every other bar as a stub too short to compare.
  const widest = Math.max(1, ...groups.map((g) => g.total));

  return (
    <div className="dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog stagedetail" role="dialog" aria-modal="true"
           aria-labelledby="stage-title" ref={panel}>
        <h2 id="stage-title">
          <span className={`stage-badge n${stage.n}`} aria-hidden="true">{stage.n}</span>
          {stage.title}
          <IconButton name="close" label="Close" className="dialog-x" onClick={close} />
        </h2>

        {/* Four bordered figures, not four words in a sentence. They are the only
            numbers in this panel and they were set as an inline run of text, which is
            the one shape that guarantees nobody compares them. */}
        <div className="stage-figures">
          <span className="figure">
            <strong>{flow?.came ?? 0}</strong>
            came in
          </span>
          <span className="figure went">
            <strong>{flow?.through ?? 0}</strong>
            went through
          </span>
          <span className="figure aside">
            <strong>{setAside}</strong>
            set aside
          </span>
          <span className="figure">
            <strong>{stage.n === 1 ? "$0.00" : `$${(cost || 0).toFixed(4)}`}</strong>
            {stage.n === 1 ? "this step is free" : "spent"}
          </span>
        </div>

        <p className="dialog-body">{PARAGRAPH[stage.n]}</p>

        {/* Both halves. The panel used to carry only the rejections, which turns an
            account of a step into a list of what it threw away. */}
        <h3 className="sub">Why it let those through</h3>
        <p className="stage-passed">{PASSED(floor)[stage.n]}</p>

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

        {groups.length > 0 && <h3 className="sub">Why it set the rest aside</h3>}

        <ul className="reasonlist">
          {groups.map((g) => {
            const mine = rows.filter((r) => r.reason === g.reason);
            const isOpen = expanded === g.reason;
            // Three, not five. The drawer is a spot check — "is this rejection right?" —
            // and five rows of a hundred is the same answer as three with more scrolling
            // between one reason and the next.
            const visible = showAll[g.reason] ? mine : mine.slice(0, 3);
            return (
              <li key={g.reason} className={`reason ${isOpen ? "on" : ""}`}>
                <button
                  type="button"
                  className="reason-head"
                  onClick={() => setExpanded(isOpen ? null : g.reason)}
                  aria-expanded={isOpen}
                >
                  <span className="reason-caret" aria-hidden="true">
                    <Icon name="chevron" size={13} />
                  </span>
                  {/* The count leads, as a clay numeral, and the bar on the right is
                      what makes "64 below your floor, 13 faith-based" legible without
                      reading either number. */}
                  <span className="reason-count">{g.total}</span>
                  <span className="reason-name">{label(g.reason)}</span>
                  <span className="reason-bar" aria-hidden="true">
                    <span className="reason-bar-fill"
                          style={{ width: `${Math.round((g.total / widest) * 100)}%` }} />
                  </span>
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
                      {/* **The funder's name is the link**, not the page title. It was
                          the other way round, which buries the one word somebody is
                          scanning for — you recognise "San Diego Foundation", not
                          "Community Enhancement Program FY26 Guidelines". */}
                      <ul className="rejectlist">
                        {visible.map((r, i) => (
                          <li key={`${r.url}-${i}`}>
                            {r.url ? (
                              <a className="reject-funder" href={r.url}
                                 target="_blank" rel="noopener noreferrer">
                                {r.funder} ↗
                              </a>
                            ) : (
                              <span className="reject-funder">{r.funder}</span>
                            )}
                            {r.title && <span className="reject-title">{r.title}</span>}
                            {r.detail && <span className="reject-detail">{r.detail}</span>}
                            {r.url && (
                              <span className="reject-host">
                                {r.url.replace(/^https?:\/\//, "").split("/")[0]}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                      {mine.length > visible.length ? (
                        <button
                          className="pill reject-more"
                          onClick={() => setShowAll({ ...showAll, [g.reason]: true })}
                        >
                          Show the other {mine.length - visible.length}
                          <Icon name="chevron" size={12} />
                        </button>
                      ) : mine.length > 3 && (
                        <button
                          className="pill reject-more on"
                          onClick={() => setShowAll({ ...showAll, [g.reason]: false })}
                        >
                          Show fewer
                          <Icon name="chevron" size={12} />
                        </button>
                      )}
                    </>
                  )
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
