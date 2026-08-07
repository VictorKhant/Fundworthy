import { useState } from "react";
import { awardRange, money, FUNDER_TYPE_LABELS } from "../api";

// One finding. The rule this component exists to enforce: a value the funder's own page
// stated and a value the model inferred must never look the same. Sourced values are
// solid sage chips; inferred ones are dashed and carry an "AI" mark. CLAUDE.md —
// "judges include working funders, a wrong deadline in the demo is fatal" — is a UI
// problem as much as a pipeline one, because a correctly-nulled field still misleads if
// the page renders a guess next to it without saying which is which.
//
// The row collapses now. Four facts decide whether a grant is worth ten hours — how well
// it fits, how much it pays, when it is due, how long it takes — and those four stay on
// the collapsed row. Everything else is still here, one click down; nothing was deleted
// to make the list shorter.

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

// What the score is made of, and what it could not be made of.
//
// The 0-100 is three parts — program fit out of 40, award size out of 35, whether the
// application can be finished in time out of 25 — and until now only the total was kept,
// so "why is this 38?" had no answer anywhere in the app. It turned out to matter: the
// two components that need the funder to have published something were unearnable on
// most pages, which capped every score near 40 and read as "we found you nothing good"
// when the real story was that grant-makers write terse pages.
//
// A component that could not be scored is not shown as a zero. It is named, with the
// points it took out of the total, because a score out of 65 and a score out of 100 are
// different claims and the reader has to be told which one they are looking at.
//
// Rows scored before the breakdown existed have no parts recorded. They show nothing
// here rather than three zeroes — see the v15 note in app/db.py.
const PART_LABEL = {
  fit_score: ["Program fit", 40],
  award_score: ["Award size", 35],
  timing_score: ["Finishing in time", 25],
};

function Breakdown({ o }) {
  if (o.fit_score == null) return null;
  const scored = [];
  const missing = [];
  for (const [key, [label, outOf]] of Object.entries(PART_LABEL)) {
    (o[key] == null ? missing : scored).push({ key, label, outOf, value: o[key] });
  }
  return (
    <div className="opp-parts">
      <span className="opp-parts-total">
        Score {o.score}
        <span className="opp-parts-unit">/100</span>
      </span>
      {scored.map((p) => (
        <span key={p.key} className="opp-part">
          {p.label} <strong>{p.value}</strong>
          <span className="opp-parts-unit">/{p.outOf}</span>
        </span>
      ))}
      {/* Named, not restated. The rationale above already carries the sentence that
          explains what a missing component means for the total (agent/score.py:
          basis_note, appended there so it survives into the CSV and the Sheet, which
          have no breakdown to render). Saying it a second time two lines further down
          was the same claim twice on one card. */}
      {missing.length > 0 && (
        <span className="opp-part off">
          {missing.map((p) => p.label).join(" and ")} — not scored
        </span>
      )}
    </div>
  );
}

export function Finding({ o, maxEffortHours = null }) {
  const [open, setOpen] = useState(false);
  const range = awardRange(o);
  const flagged = !!o.needs_human_check;
  // The org's own hours-per-application figure, not a constant. It was hardcoded 10
  // here while the setting it mirrors became per-org, so a nonprofit that told us it
  // can spend 40 hours saw "~25h to apply — over the 10-hour cap" on a row the model
  // had just scored as comfortably feasible: the badge contradicted the score beside it.
  //
  // Null means this caller does not know the figure. Then we say nothing rather than
  // measure against a number we invented — the same rule as the rest of the card.
  const overCap =
    maxEffortHours != null &&
    o.estimated_effort_hours != null &&
    o.estimated_effort_hours > maxEffortHours;

  return (
    <article className={`opp ${flagged ? "flagged" : ""}`}>
      <div className="opp-row">
        {/* The headline number is the AI's fit judgement — how well this funder matches
            a programme — because that is the question the user is actually asking when they
            scan the list. The 0-100 rank score is what the list is ordered by and lives
            one click down.

            It is drawn as an inferred value (dashed rule, "AI" label) and not in the
            solid sage used for sourced figures. That rule matters more here than
            anywhere else on the card: this is the largest, most confident-looking number
            on the row, and nothing about it was read off the funder's page. */}
        <div
          className="opp-score inferred"
          title={
            o.confidence_pct != null
              ? "The AI's confidence that this funder would fund one of your programs. " +
                "Its own judgement — not a figure from the funder's page."
              : "The AI did not give a fit estimate for this one."
          }
        >
          {o.confidence_pct != null ? `${o.confidence_pct}%` : "—"}
          <span className="opp-score-tag">fit · AI</span>
          {/* The rank, back on the collapsed row.
              The list says "ranked best first" and is sorted by score — but once the
              card collapsed to four facts, the score moved behind "More details" and the
              only visible number became fit. On real data that reads 12%, 18%, 3% down
              the page, so the ordering looks arbitrary and the first question anyone
              asks is why 12 is above 18. A list whose order has no visible cause reads
              as broken; this is the cheapest possible way to give it one. */}
          <span className="opp-rank" title="Score out of 100 — what this list is ranked by">
            {o.score}<span className="opp-rank-unit">/100</span>
          </span>
        </div>

        <div className="opp-body">
          <div className="opp-head">
            <span className="opp-funder">{o.funder}</span>
            {/* Where it came from. A funder page is an organisation already on the list,
                read directly; a database row is a public list nobody curated. Same
                accuracy rules either way, but very different starting positions for a
                conversation, so it belongs on the collapsed row. */}
            {o.source_kind === "indexed_database" && (
              <span className="chip" title="Found in a public grants database, not on a funder's own page">
                Public database
              </span>
            )}
            {flagged && (
              <span className="chip warn" title="The AI reported something it could not confirm against the funder's page, so we removed the value">
                Unverified claim
              </span>
            )}
          </div>

          <div className="opp-title">{o.title}</div>

          <div className="opp-meta">
            {range ? (
              <span className="chip strong">{range}</span>
            ) : (
              <span className="chip muted">Amount not stated</span>
            )}
            <Deadline o={o} />
            {/* Effort shows on every row, always. The scoring model is required to give a
                number (agent/score.py), so a blank here means a row scored before that
                rule existed — say so rather than rendering nothing, because a missing
                chip is indistinguishable from a quick application at a glance, and
                whether an application fits the hours they have is the decision this
                whole list exists to serve. */}
            {o.estimated_effort_hours != null ? (
              <Inferred
                title={
                  overCap
                    ? `Estimated effort for a competitive application — over the ${maxEffortHours}h you said you can spend on one`
                    : "Estimated effort for a competitive application"
                }
              >
                ~{o.estimated_effort_hours}h to apply
                {overCap && ` — over your ${maxEffortHours}h`}
              </Inferred>
            ) : (
              <span className="chip muted" title="Scored before effort estimates were required. Re-run the search to fill it in.">
                Effort not estimated
              </span>
            )}
          </div>

          {/* Opening the funder's own page is the entire point of the flagged section,
              so for those rows the link does not hide behind a disclosure. */}
          {flagged && (
            <div className="opp-meta">
              <a href={o.source_url} target="_blank" rel="noopener noreferrer">
                Check the listing yourself ↗
              </a>
              <span className="muted small">Found {o.found_on}</span>
            </div>
          )}
        </div>

        <button
          className="text opp-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          {open ? "Less" : "More details"}
        </button>
      </div>

      {open && (
        <div className="opp-detail">
          {o.score_rationale && (
            <p className="opp-why">
              <em className="opp-why-label">Why it scored this way · AI</em> —{" "}
              {o.score_rationale}
            </p>
          )}

          <Breakdown o={o} />

          <div className="opp-meta">
            {o.award_typical != null && (
              <span className="chip">Typically {money(o.award_typical)}</span>
            )}
            {/* Calendar time to BE READY to submit. Different from effort hours: audited
                financials and board resolutions depend on other people and add weeks no
                hours estimate sees. Against the deadline this is the COO's "due in 2
                weeks but the application takes 3 weeks" case. */}
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
            {/* The ranking number. It is not on the collapsed row — fit is the question
                being asked there — but it cannot vanish either: it is what this list is
                sorted by, and a list whose order has no visible cause reads as arbitrary.

                This used to read "provisional … award size is 35% of the score", which
                the composition change made false in the exact direction that matters. A
                missing component is no longer scored zero and no longer costs the row
                35 points; it is dropped from the denominator (agent/score.py:
                compose_score), so the score is out of fewer parts rather than short of a
                third of its basis. Saying "provisional" beside a breakdown that says
                "left out rather than counted against it" was one card making two
                opposite claims about the same number. */}
            <Inferred
              title={
                o.section === "scored"
                  ? "Score out of 100. What this list is ranked by, weighted per CLAUDE.md."
                  : "Score out of 100, scored on fewer parts. The funder's page stated no " +
                    "award amount, so award size was left out of the total rather than " +
                    "counted against it — the breakdown above says what it was scored on."
              }
            >
              Rank score {o.score}
              {o.section !== "scored" && " · not scored on award size"}
            </Inferred>
            {o.funder_type && o.funder_type !== "unknown" && (
              <Inferred>{FUNDER_TYPE_LABELS[o.funder_type] || o.funder_type}</Inferred>
            )}
            {o.geography && <span className="chip">{o.geography}</span>}
            {o.service_areas?.length > 0 && (
              <Inferred>{o.service_areas.join(" · ")}</Inferred>
            )}
            {o.program_match?.length > 0 && (
              <span className="chip">For: {o.program_match.join(", ")}</span>
            )}
            {o.contact_note && <span className="chip">{o.contact_note}</span>}
          </div>

          <div className="opp-links">
            <a href={o.source_url} target="_blank" rel="noopener noreferrer" className="strong-link">
              Open the funder's page ↗
            </a>
            {/* Flagged rows already carry this on the collapsed footer, next to the
                link they exist to push you towards. */}
            {!flagged && <span className="muted">Found {o.found_on}</span>}
          </div>
        </div>
      )}
    </article>
  );
}

// The two blocks the user asked for, in their order: everything the agent is confident about
// first, everything it wants a second opinion on at the very bottom. The backend already
// sorts this way, so the split here is presentational only — the order is enforced in
// SQL so every surface agrees.
// `helper` is the first-run orientation banner, passed in from the dashboard rather than
// rendered at the top of the page. What it explains — the AI/sourced split — is marked
// inline on every row below it, so it belongs against those rows and not in the position
// the eye lands on first.
export default function Findings({ clear = [], needsCheck = [], emptyBody, helper = null,
                                   maxEffortHours = null }) {
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
      <section className="findings">
        <h2>Worth a look — {clear.length}</h2>
        <p className="findings-note">
          Ranked best first. "Not stated" means the funder's page didn't say — the
          researcher never guesses.
        </p>
        {helper}
        {clear.length === 0 ? (
          <p className="muted small">
            Nothing came through clean this time. That can be a perfectly good week — the
            list below is what needs a decision from you.
          </p>
        ) : (
          <div className="opps">
            {clear.map((o) => (
              <Finding key={o.id} o={o} maxEffortHours={maxEffortHours} />
            ))}
          </div>
        )}
      </section>

      {needsCheck.length > 0 && (
        <section className="findings">
          <h2>Needs your eyes — {needsCheck.length}</h2>
          <p className="findings-note">
            The researcher reported something it could <strong>not</strong> confirm on the
            funder's page, so the value was removed rather than shown. Worth opening the
            link yourself. It should be rare; if it is not, tell us, because it means the
            reading step is drifting.
          </p>
          <div className="opps">
            {needsCheck.map((o) => (
              <Finding key={o.id} o={o} maxEffortHours={maxEffortHours} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
