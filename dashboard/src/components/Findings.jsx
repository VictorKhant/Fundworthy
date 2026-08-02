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
      {/* The headline number is the AI's fit judgement — how well this funder matches a
          RISE programme — because that is the question Mauri is actually asking when she
          scans the list. The 0-100 score is still what the list is ranked by, so it
          stays on the card, one row down.

          It is drawn as an inferred value (dashed, "AI" tag) and not in the accent
          colour used for sourced figures. That is the B7 rule and it matters more here
          than anywhere else on the card: this is the largest, most confident-looking
          number on the row, and nothing about it was read off the funder's page. */}
      <div
        className="opp-score inferred"
        title={
          o.confidence_pct != null
            ? "The AI's confidence that this funder would fund a RISE program. Its own " +
              "judgement — not a figure from the funder's page."
            : "The AI did not give a fit estimate for this one."
        }
      >
        {o.confidence_pct != null ? `${o.confidence_pct}%` : "—"}
        <span className="opp-score-tag">fit · AI</span>
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
            <span className="chip warn" title="The AI reported something it could not confirm against the funder's page, so we removed the value">
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
          {/* Effort shows on every row, always. The scoring model is now required to
              give a number (agent/score.py), so a blank here means a row scored before
              that rule existed — say so rather than rendering nothing, because a missing
              chip is indistinguishable from a quick application at a glance, and the
              10-hour cap is the decision this whole list exists to serve. */}
          {o.estimated_effort_hours != null ? (
            <Inferred
              title={
                o.estimated_effort_hours > 10
                  ? "Estimated effort for a competitive application — over the 10-hour cap"
                  : "Estimated effort for a competitive application"
              }
            >
              ~{o.estimated_effort_hours}h to apply
              {o.estimated_effort_hours > 10 && " — over the 10-hour cap"}
            </Inferred>
          ) : (
            <span className="chip muted" title="Scored before effort estimates were required. Re-run the search to fill it in.">
              Effort not estimated
            </span>
          )}
          {/* Calendar time to BE READY to submit. Different from effort hours:
              audited financials and board resolutions depend on other people and add
              weeks no hours estimate sees. Against the deadline this is the COO's
              "due in 2 weeks but the application takes 3 weeks" case. */}
          {o.application_lead_time_days != null && (
            <Inferred title="Calendar days needed to prepare and submit, given what the application requires from other people">
              ~{o.application_lead_time_days}d to prepare
              {o.days_left != null && o.application_lead_time_days > o.days_left &&
                " — longer than the time left"}
            </Inferred>
          )}
          {o.time_to_funds_days != null && (
            <Inferred title="Estimated days from submitting to the money reaching the bank — a nonprofit's cash flow depends on this and funders rarely state it">
              ~{Math.round(o.time_to_funds_days / 30)} months to funds
            </Inferred>
          )}
          {/* The ranking number. It moved off the badge to make room for the fit
              percentage, but it cannot just vanish — it is what this list is sorted by,
              and a list whose order has no visible cause reads as arbitrary.

              "Provisional" when the funder's page stated no award amount: award size is
              35 of the 100 points (CLAUDE.md §7), so that score is missing over a third
              of its own basis and is not comparable to a fully sourced one. */}
          <Inferred
            title={
              o.section === "scored"
                ? "Score out of 100. What this list is ranked by, weighted per CLAUDE.md §7."
                : "Score out of 100 — provisional. The funder's page did not state an " +
                  "award amount, and award size is 35% of the score."
            }
          >
            Score {o.score}
            {o.section !== "scored" && " · provisional"}
          </Inferred>
        </div>

        <div className="opp-meta">
          {o.geography && <span className="chip">{o.geography}</span>}
          {o.service_areas?.length > 0 && (
            <Inferred>{o.service_areas.join(" · ")}</Inferred>
          )}
          {o.program_match?.length > 0 && (
            <span className="chip">For: {o.program_match.join(", ")}</span>
          )}
          {/* Shown as data, never scored — the COO's own call. It is here so a
              funder that reads big on its own website can be checked against what it
              actually files. */}
          {o.form_990_url && (
            <a className="chip" href={o.form_990_url} target="_blank" rel="noopener noreferrer">
              {o.form_990_total_expenses
                ? `990: ${money(o.form_990_total_expenses)} spent in ${o.form_990_year} ↗`
                : "View their 990 ↗"}
            </a>
          )}
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
          Ranked best first, out of 100. Everything here cleared your award floor. Where
          a funder did not publish an amount or a deadline you will see "not stated"
          rather than a guess — that is normal, and the score already accounts for it.
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
