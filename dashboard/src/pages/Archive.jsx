import { useEffect, useState } from "react";
import { api, awardRange, usd } from "../api";
import DownloadCsv from "../components/DownloadCsv";
import Icon from "../components/Icon";
import Spinner from "../components/Spinner";

// Archived findings — one entry per SEARCH, not one pooled list per month.
//
// It used to be a single list for the whole month, the same shape as This week but with
// a month picker on top. That answered "what did we find in August" and nothing else —
// which programs a given search was matching against, which funder lists it actually
// read, how many of a search's own results are still on the list — none of that
// survived past the run itself. Two searches three weeks apart, against different
// ticked programs and different funder lists, looked like one undifferentiated pile.
//
// The archive is still deliberately short-lived — the current month plus whatever
// `available_months` still holds — for the same reason as before: it is what stops the
// same grant reappearing every week forever, and what lets something still open next
// month get a second look.

const monthName = (key) => {
  if (!key) return "";
  const [y, m] = key.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
};

function dayAndTime(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return { day: "", time: "" };
  return {
    day: d.toLocaleDateString(undefined, {
      weekday: "long", day: "numeric", month: "long",
    }),
    time: d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
      .replace(" ", "").toLowerCase(),
  };
}

function SearchFinding({ o, programBySlug }) {
  const range = awardRange(o);
  const due = o.deadline_type === "rolling"
    ? "Rolling deadline"
    : o.deadline ? `Due ${o.deadline}` : "Deadline not stated";
  const matched = (o.program_match || []).map((slug) => programBySlug[slug] || slug);

  return (
    <div className="search-finding">
      <span className="search-finding-score">{o.score}%</span>
      <div className="search-finding-body">
        <strong>{o.funder}</strong>
        <p className="search-finding-title">{o.title}</p>
        <p className="muted small">{range || "Amount not stated"} · {due}</p>
      </div>
      {matched.length > 0 && (
        <span className="pill search-finding-match">Matched {matched.join(", ")}</span>
      )}
      <a className="search-finding-link" href={o.source_url}
         target="_blank" rel="noopener noreferrer"
         title="Open the funder's page" aria-label={`Open ${o.funder}'s page`}>
        <Icon name="chevron" size={13} />
      </a>
    </div>
  );
}

function SearchCard({ search, month }) {
  const [open, setOpen] = useState(false);
  const [findings, setFindings] = useState(null);
  const [error, setError] = useState(null);

  const { day, time } = dayAndTime(search.started_at);
  const trigger = search.trigger === "scheduled"
    ? "Ran on its own, weekly"
    : 'You pressed "Search again now"';
  const programs = search.programs_snapshot || [];
  const groups = search.funder_groups || [];
  const funderCount = groups.reduce((n, g) => n + g.count, 0);
  const programBySlug = Object.fromEntries(programs.map((p) => [p.slug, p.name]));

  async function toggle() {
    if (!open && findings === null) {
      try {
        const res = await api.opportunities(month, search.id);
        setFindings([...(res.clear || []), ...(res.needs_check || [])]);
      } catch (e) {
        setError(e.message);
      }
    }
    setOpen(!open);
  }

  return (
    <div className="search-card">
      <div className="search-card-head">
        <div>
          <h3>{day} <span className="muted search-card-time">{time}</span></h3>
          <p className="muted small">{trigger}</p>
        </div>
        <div className="search-card-stats">
          <div className="search-stat">
            <strong>{funderCount}</strong>
            <span>funders read</span>
          </div>
          <div className="search-stat">
            <strong className="ok">{search.kept_count}</strong>
            <span>worth a look</span>
          </div>
          <div className="search-stat">
            <strong>{usd(search.usd_spent)}</strong>
            <span>of your key</span>
          </div>
        </div>
      </div>

      <div className="search-card-boxes">
        <div className="search-box">
          <div className="search-box-head">
            Program cards searched for — {programs.length}
          </div>
          <div className="search-box-chips">
            {programs.length === 0 ? (
              <span className="muted small">None ticked for this search.</span>
            ) : programs.map((p) => (
              <span key={p.slug} className="chip on">✓ {p.name}</span>
            ))}
          </div>
        </div>
        <div className="search-box">
          <div className="search-box-head">Funder lists read — {groups.length}</div>
          <div className="search-box-chips">
            {groups.length === 0 ? (
              <span className="muted small">Nothing read for this search.</span>
            ) : groups.map((g) => (
              <span key={g.label} className="chip on">✓ {g.label} · {g.count}</span>
            ))}
          </div>
        </div>
      </div>

      <button type="button" className="text search-toggle" onClick={toggle}
              aria-expanded={open}>
        {open ? "Hide these findings" : (
          search.kept_count > 0
            ? `Show the ${search.kept_count} finding${search.kept_count === 1 ? "" : "s"} from this search`
            : "Nothing was kept from this search"
        )}
        {search.kept_count > 0 && (
          <span className={`search-toggle-caret ${open ? "on" : ""}`} aria-hidden="true">
            <Icon name="chevron" size={12} />
          </span>
        )}
      </button>

      {open && (
        <div className="search-findings">
          {error && <div className="notice error">{error}</div>}
          {findings === null && !error && (
            <p className="loading-line small">
              <Spinner label="Loading this search's findings" size={13} />
              Loading…
            </p>
          )}
          {findings?.length === 0 && (
            <p className="muted small">Nothing was recorded for this search.</p>
          )}
          {findings?.map((o) => (
            <SearchFinding key={o.id} o={o} programBySlug={programBySlug} />
          ))}
          {findings && findings.length > 0 && (
            <p className="muted small search-findings-footer">
              {search.kept_count} kept from {funderCount} funders read, against{" "}
              {programs.length} ticked program card{programs.length === 1 ? "" : "s"}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

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
          <h1>Past findings</h1>
        </header>
        <div className="notice error">{error}</div>
      </>
    );
  }

  if (!data) {
    return (
      <p className="loading-line">
        <Spinner label="Loading the archive" />
        Loading this month's findings…
      </p>
    );
  }

  const searches = data.searches || [];
  const totalKept = searches.reduce((n, s) => n + (s.kept_count || 0), 0);
  const totalSpent = searches.reduce((n, s) => n + (s.usd_spent || 0), 0);

  return (
    <>
      <header>
        <h1>Past findings</h1>
        <p className="muted small">
          One entry per search, kept separate. Each one shows the program cards it was
          matching against and the funder lists it read at the time — so two searches in
          the same month are not the same search. Anything older than twelve months is
          removed.
        </p>
      </header>

      <div className="row archive-months">
        {data.months?.length === 0 ? (
          <p className="muted small">Nothing archived yet. Run a search on This week.</p>
        ) : (
          data.months.map((m) => (
            <button
              key={m.month_key}
              className={`pill ${m.month_key === month ? "dark" : ""}`}
              onClick={() => setMonth(m.month_key)}
            >
              {monthName(m.month_key)}
              {m.month_key === data.current_month && " (this month)"}
            </button>
          ))
        )}
      </div>

      {month && (
        <>
          <div className="archive-month-summary">
            <h2>{monthName(month)}</h2>
            <span className="muted">
              {searches.length} search{searches.length === 1 ? "" : "es"} ·{" "}
              {totalKept} finding{totalKept === 1 ? "" : "s"} kept ·{" "}
              {usd(totalSpent)} of your key
            </span>
            {(data.opportunities || []).length > 0 && <DownloadCsv month={month} />}
          </div>

          <div className="archive-note">
            The archive keeps the current month. When a search runs in a new month, the
            previous month's rows are cleared — that is what stops you being shown the
            same grant every week, and it means anything still open gets a fresh look
            next month rather than being hidden forever.
          </div>

          {searches.length === 0 ? (
            <p className="muted small">No searches recorded for {monthName(month)}.</p>
          ) : (
            <div className="search-cards">
              {searches.map((s) => (
                <SearchCard key={s.id} search={s} month={month} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
