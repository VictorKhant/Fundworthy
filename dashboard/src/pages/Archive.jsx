import { useEffect, useState } from "react";
import { api } from "../api";
import Findings from "../components/Findings";

// Archived findings.
//
// The archive is deliberately short-lived: it holds the current month, and everything
// older is deleted when a search runs in a new month. That is not a limitation we ran
// out of time to fix — it is what makes "don't show me the same grant four Thursdays
// running" work without the list growing forever, and it means a grant that is still
// open next month gets a second look rather than being suppressed permanently. The page
// says so, because a person who does not know that would reasonably think data was lost.

const monthName = (key) => {
  if (!key) return "";
  const [y, m] = key.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
};

export default function Archive() {
  const [data, setData] = useState(null);
  const [month, setMonth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .archive(month)
      .then((d) => {
        setData(d);
        if (!month && d.months_available?.length) setMonth(d.months_available[0]);
      })
      .catch((e) => setError(e.message));
  }, [month]);

  if (error) {
    return (
      <>
        <header>
          <h1>Archived findings</h1>
        </header>
        <div className="notice error">{error}</div>
      </>
    );
  }

  if (!data) return <p className="muted">Loading…</p>;

  const rows = data.opportunities || [];
  const clear = rows.filter((o) => !o.needs_human_check);
  const needsCheck = rows.filter((o) => o.needs_human_check);

  return (
    <>
      <header>
        <div className="panel-head">
          <h1>Archived findings</h1>
          {/* Downloads the month currently selected below, not today's — otherwise
              picking August and getting July's file is a silent wrong answer. */}
          {rows.length > 0 && (
            <a className="button" href={api.exportUrl(month)} download>
              Download as a spreadsheet
            </a>
          )}
        </div>
        <p className="muted">
          Everything found this month, including what you have already reviewed.
        </p>
      </header>

      <section className="panel">
        <h2>By month</h2>
        {data.months?.length === 0 ? (
          <p className="muted">Nothing archived yet. Run a search on the main page.</p>
        ) : (
          <div className="checks">
            {data.months.map((m) => (
              <button
                key={m.month_key}
                className={m.month_key === month ? "primary" : "ghost"}
                onClick={() => setMonth(m.month_key)}
              >
                {monthName(m.month_key)} — {m.total}
                {m.month_key === data.current_month && " (this month)"}
              </button>
            ))}
          </div>
        )}
        <p className="muted small">
          The archive keeps the current month. When a search runs in a new month, the
          previous month's rows are cleared — that is what stops you being shown the same
          grant every week, and it means anything still open gets a fresh look next month
          rather than being hidden forever.
        </p>
      </section>

      {month && (
        <Findings
          clear={clear}
          needsCheck={needsCheck}
          emptyBody={`Nothing was recorded for ${monthName(month)}.`}
        />
      )}
    </>
  );
}
