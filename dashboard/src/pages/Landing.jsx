// The public landing page. Nothing here talks to the API — it is copy and a hand-built
// mock of the findings list, using the same chip classes the real list uses so the
// example on the marketing page cannot drift from the product.
//
// The honesty section is not marketing garnish. "Amount not stated instead of a guessed
// number" and "AI judgements carry a visible AI mark" are the two rules from CLAUDE.md §6
// that the whole pipeline is arranged around, and stating them up front is what earns the
// short list its credibility.

const HOW = [
  {
    n: "1 — Tell it about your work",
    body:
      "Paste a link to each of your programs. The assistant reads the page and fills in " +
      "the details for you to correct — you never write a prompt.",
  },
  {
    n: "2 — It searches every week",
    body:
      "It reads your funder list and public grant databases on a schedule, filters out " +
      "anything too small or due too soon, and scores the rest.",
  },
  {
    n: "3 — You review a short list",
    body:
      "A ranked list sized for a one-hour review, with the deadline, the amount, and how " +
      "long the application takes. You decide what's worth it.",
  },
];

const PRINCIPLES = [
  '"Amount not stated" instead of a guessed number',
  'AI judgements carry a visible "AI" mark, always',
  "Anything below your award floor is filtered out for free",
  "One switch turns the whole thing off — no calls, no terminal",
];

// The hero's example list. Invented funders and figures, shown as a product mock — which
// is why it is here in the marketing page and never rendered by Findings.jsx.
const SAMPLE = [
  {
    fit: "82%", funder: "Prebys Foundation",
    title: "Community Impact Grants — Arts & Culture",
    amount: "$50,000–$150,000", deadline: "Due Sep 15",
  },
  {
    fit: "74%", funder: "California Arts Council",
    title: "Impact Projects — Community Engagement",
    amount: "$10,000–$40,000", deadline: "Due Aug 20",
  },
  {
    fit: "61%", funder: "The Parker Foundation",
    title: "General Community Grants",
    amount: null, deadline: "Rolling",
  },
];

export default function Landing({ onSignIn, onCreate }) {
  return (
    <div className="lp">
      <nav className="lp-nav">
        <div className="brandmark lp-brand">
          Fundworthy
          <span className="brand-dot" aria-hidden="true" />
        </div>
        <div className="lp-navlinks">
          <a href="#how">How it works</a>
          <a href="#cost">What it costs</a>
          <button className="text lp-signin" onClick={onSignIn}>Sign in</button>
          <button className="primary" onClick={onCreate}>Create an account</button>
        </div>
      </nav>

      <header className="lp-hero">
        <div>
          <p className="lp-eyebrow">For small nonprofits</p>
          <h1 className="lp-h1">
            Your weekly grant researcher, <em>for about a dollar.</em>
          </h1>
          <p className="lp-lede">
            Every week it reads the funders you care about and leaves you a short, ranked
            list of what is actually worth applying for — usually 10+ opportunities, each
            one sourced from the funder's own page.
          </p>
          <div className="lp-cta">
            <button className="dark lp-bigbtn" onClick={onCreate}>Start finding funding</button>
            <a href="#how" className="lp-ghostlink">See how it works →</a>
          </div>
          <p className="lp-fineprint">
            First built with RISE San Diego. No credit card — you bring your own AI key.
          </p>
        </div>

        <div className="lp-mock">
          <div className="lp-mock-head">
            <span className="lp-mock-title">This week — 3 worth a look</span>
            <span className="chip strong">$0.60 spent of $1.00</span>
          </div>
          <div className="opps">
            {SAMPLE.map((s) => (
              <div className="lp-mock-row" key={s.funder}>
                <div className="opp-score inferred lp-mock-score">
                  {s.fit}
                  <span className="opp-score-tag">fit · AI</span>
                </div>
                <div>
                  <div className="opp-funder">{s.funder}</div>
                  <div className="opp-title">{s.title}</div>
                  <div className="opp-meta">
                    {s.amount ? (
                      <span className="chip strong">{s.amount}</span>
                    ) : (
                      <span className="chip muted">Amount not stated</span>
                    )}
                    <span className="chip">{s.deadline}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="lp-mock-foot">
            When a funder doesn't state a number, it says so — it never guesses.
          </p>
        </div>
      </header>

      <section id="how" className="lp-section">
        <h2 className="lp-h2">How it works</h2>
        <p className="lp-sub">
          No prompts to write, no spreadsheets to build. Set it up once, then read a short
          list every week.
        </p>
        <div className="lp-three">
          {HOW.map((h) => (
            <div className="lp-card" key={h.n}>
              <div className="lp-step">{h.n}</div>
              <p>{h.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-band">
        <div className="lp-band-inner">
          <div>
            <h2 className="lp-h2">Few results, honestly sourced</h2>
            <p className="lp-sub">
              Finding grants was never the hard part — deciding which are worth ten hours
              is. So Fundworthy returns <em className="lp-em">few</em> results, and marks
              every value the AI judged rather than read off the funder's page.
            </p>
          </div>
          <ul className="lp-principles">
            {PRINCIPLES.map((p) => (
              <li key={p}>
                <span aria-hidden="true">·</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section id="cost" className="lp-section lp-centered">
        <h2 className="lp-h2">What it costs</h2>
        <p className="lp-sub">
          Fundworthy is free. You bring your own Claude API key, and each weekly search
          costs about <strong>$1</strong> — with a spending ceiling you set. It stops
          itself rather than going over.
        </p>
        <div className="lp-stats">
          <div>
            <div className="lp-stat">~$1</div>
            <div className="lp-statlabel">per weekly search</div>
          </div>
          <div className="lp-statrule" />
          <div>
            <div className="lp-stat">10+</div>
            <div className="lp-statlabel">opportunities found</div>
          </div>
          <div className="lp-statrule" />
          <div>
            <div className="lp-stat">$0</div>
            <div className="lp-statlabel">subscription, ever</div>
          </div>
        </div>
        <div className="lp-cta lp-cta-center">
          <button className="primary lp-bigbtn" onClick={onCreate}>Create your account</button>
        </div>
      </section>

      <footer className="lp-footer">
        <span className="lp-footmark">Fundworthy</span>
        <span>
          First built with RISE San Diego at the AI Trailblazers Social Impact
          Hack-AI-thon, 2026.
        </span>
      </footer>
    </div>
  );
}
