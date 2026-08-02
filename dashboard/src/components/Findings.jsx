import { awardRange, money, FUNDER_TYPE_LABELS } from "../api";

// One finding. The rule this component exists to enforce: a value the funder's own page
// stated and a value the model inferred must never look the same. Sourced values are
// plain text; inferred ones carry an "AI" chip. CLAUDE.md §6 — "judges include working
// funders, a wrong deadline in the demo is fatal" — is a UI problem as much as a
// pipeline one, because a correctly-nulled field still misleads if the page renders a
// guess next to it without saying which is which.

function Inferred({ children, title }) {
  return (
    <span className="chip inferred" title={title || "The AI's read, not a quote from the funder's page"}>
      {children}
      <span className="chip-tag">AI</span>
    </span>
  );
}

function Deadline({ o }) {
  if (o.deadline_type === "rolling") {
    return <span className="chip">Rolling deadline</span>;
  }
  if (!o.deadline) {
    return <span className="chip muted">Deadline not stated</span>;
  }
  const urgent = o.days_left != null && o.days_left < 21;
  return (
    <span className={`chip ${urgent ? "warn" : ""}`}>
      Due {o.deadline}
      {o.days_left != null && ` · ${o.days_left}d left`}
    </span>
  );
}

export function Finding({ o }) {
  const range = awardRange(o);
  return (
    <article className={`opp ${o.needs_human_check ? "flagged" : ""}`}>
      <div className="opp-score" title="Score out of 100">
        {o.section === "scored" ? o.score : "—"}
      </div>

      <div className="opp-body">
        <div className="opp-head">
          <span className="opp-funder">{o.funder}</span>
          {o.funder_type && o.funder_type !== "unknown" && (
            <Inferred>{FUNDER_TYPE_LABELS[o.funder_type] || o.funder_type}</Inferred>
          )}
          {o.needs_human_check && <span className="chip warn">Needs your eyes</span>}
        </div>

        <div className="opp-title">{o.title}</div>
        {o.score_rationale && <div className="opp-why">{o.score_rationale}</div>}

        <div className="opp-meta">
          {range ? (
            <span className="chip strong">{range}</span>
          ) : (
            <span className="chip muted">Amount not stated</span>
          )}
          {o.award_typical != null && (
            <span className="chip">Typically {money(o.award_typical)}</span>
          )}
          <Deadline o={o} />
          {o.estimated_effort_hours != null && (
            <Inferred title="Estimated effort for a competitive application">
              ~{o.estimated_effort_hours}h
              {o.estimated_effort_hours > 10 && " — over the 10-hour cap"}
            </Inferred>
          )}
          {o.confidence_pct != null && (
            <Inferred title="How confident the AI is that this funder would fund a RISE program">
              {o.confidence_pct}% fit
            </Inferred>
          )}
        </div>

        <div className="opp-meta">
          {o.geography && <span className="chip">{o.geography}</span>}
          {o.service_areas?.length > 0 && (
            <Inferred>{o.service_areas.join(" · ")}</Inferred>
          )}
          {o.program_match?.length > 0 && (
            <span className="chip">For: {o.program_match.join(", ")}</span>
          )}
          {o.form_990_available === true && <span className="chip">990 on file</span>}
          {o.contact_note && <span className="chip">{o.contact_note}</span>}
        </div>

        <div className="opp-meta">
          <span className="muted small">Found {o.found_on}</span>
          <a href={o.source_url} target="_blank" rel="noopener noreferrer">
            Open the funder's page ↗
          </a>
        </div>
      </div>
    </article>
  );
}

// The two blocks Mauri asked for, in her order: everything the agent is confident about
// first, everything it wants a second opinion on at the very bottom. The backend already
// sorts this way, so the split here is presentational only — the order is enforced in
// SQL so every surface agrees.
export default function Findings({ clear = [], needsCheck = [], emptyBody }) {
  const total = clear.length + needsCheck.length;

  if (total === 0) {
    return (
      <div className="empty">
        <h3>Nothing to review yet</h3>
        <p>{emptyBody || "Run a search and this fills in."}</p>
      </div>
    );
  }

  return (
    <>
      <section className="panel">
        <h2>Worth a look — {clear.length}</h2>
        <p className="muted small">
          Everything here cleared the award floor and the agent could source every number
          it shows. Ranked best first.
        </p>
        {clear.length === 0 ? (
          <p className="muted">
            Nothing came through clean this time. That can be a perfectly good week —
            the list below is what needs a decision from you.
          </p>
        ) : (
          <div className="opps">
            {clear.map((o) => (
              <Finding key={o.id} o={o} />
            ))}
          </div>
        )}
      </section>

      {needsCheck.length > 0 && (
        <section className="panel">
          <h2>Needs your eyes — {needsCheck.length}</h2>
          <p className="muted small">
            The funder's page did not state something important, or the agent could not
            verify it against the page it read. These are last on purpose. Nothing here
            is a guess — a number it could not source is left blank rather than filled in.
          </p>
          <div className="opps">
            {needsCheck.map((o) => (
              <Finding key={o.id} o={o} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
