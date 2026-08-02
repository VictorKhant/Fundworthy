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
      {/* Always show the score. This used to render "—" whenever the funder had not
          published an award amount, which hid the score on 4 of 5 results in the last
          real run — including the three highest-scoring ones. The score is a judgement
          about the whole opportunity; whether the page happened to state a dollar
          figure is a separate fact, shown below as its own chip. */}
      <div className="opp-score" title="Score out of 100">
        {o.score}
      </div>

      <div className="opp-body">
        <div className="opp-head">
          <span className="opp-funder">{o.funder}</span>
          {/* Where it came from. A funder page is an organisation RISE already knows,
              read directly; a database row is a complete public list nobody curated.
              Same accuracy rules either way, but very different starting positions for
              a conversation, so it belongs on the row rather than inferred later. */}
          {o.source_kind === "indexed_database" && (
            <span className="chip" title="Found in a public grants database, not on a funder's own page">
              Public database
            </span>
          )}
          {o.funder_type && o.funder_type !== "unknown" && (
            <Inferred>{FUNDER_TYPE_LABELS[o.funder_type] || o.funder_type}</Inferred>
          )}
          {o.needs_human_check && (
            <span className="chip warn" title="The AI reported something it could not confirm against the funder's page, so we removed it">
              Unverified claim
            </span>
          )}
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
          Ranked best first, out of 100. Everything here cleared your award floor.
          Where a funder did not publish an amount or a deadline, you will see "not
          stated" rather than a guess — that is normal, and the score already accounts
          for it.
        </p>
        {clear.length === 0 ? (
          <p className="muted">
            Nothing came through clean this time. That can be a perfectly good week.
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
            For these, the AI reported something it could <strong>not</strong> confirm
            against the funder's own page — so we removed the value rather than show it.
            That is the one case worth opening the link yourself. It should be rare; if
            it is not, tell us, because it means the reading step is drifting.
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
