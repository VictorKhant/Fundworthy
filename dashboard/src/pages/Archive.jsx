import { useEffect, useState } from "react";
import { api, dayAndTime, usd } from "../api";
import { useConfirm } from "../components/Confirm";
import DownloadCsv from "../components/DownloadCsv";
import { Finding } from "../components/Findings";
import Icon from "../components/Icon";
import Spinner, { Busy } from "../components/Spinner";

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
//
// Findings render with the exact same `Finding` card `This week` uses — not a
// second, compact list style. A hand-built compact row broke outright the first time a
// funder name and a long "Matched X, Y, Z" pill both had to fit one line; the real
// card already handles long text, chips that wrap, and the AI/sourced split correctly,
// because it is the one that has actually been used.

const monthName = (key) => {
  if (!key) return "";
  const [y, m] = key.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
};

function SearchCard({ search, month, maxEffortHours, onDeleted }) {
  const [open, setOpen] = useState(false);
  const [findings, setFindings] = useState(null);
  const [error, setError] = useState(null);
  const [dialog, ask] = useConfirm();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  const { day, time } = dayAndTime(search.started_at);
  const trigger = search.trigger === "scheduled"
    ? "Ran on its own, weekly"
    : 'You pressed "Search again now"';
  const programs = search.programs_snapshot || [];
  const groups = search.funder_groups || [];
  const funderCount = groups.reduce((n, g) => n + g.count, 0);
  // A search that passed preflight and actually ran always has at least one ticked
  // program in its snapshot — so an empty one here can only mean one thing: this
  // search ran before Fundworthy started recording the breakdown at all (schema v19).
  // It is not that nothing was ticked or nothing was read; we simply never asked. Two
  // different facts, and showing "0 ticked" for the second would be a guess dressed as
  // a fact — the same rule this app applies to a funder's own page, applied to itself.
  const hasBreakdown = programs.length > 0;

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

  // Two dialogs, deliberately, not one with a typed field like Close your account — a
  // single search is a smaller, more common action than the one truly irreversible
  // thing in the app, so it earns a second plain "are you sure" rather than typing
  // anything. Both still go through the app's own themed Confirm, never
  // window.confirm.
  async function handleDelete() {
    setDeleteError(null);
    const first = await ask({
      tone: "clay",
      icon: "bin",
      title: "Delete this search?",
      body: `This permanently removes ${day} ${time} from Past findings and the ` +
            "database.",
      points: [
        search.kept_count > 0
          ? `${search.kept_count} finding${search.kept_count === 1 ? "" : "s"} from ` +
            "this search are deleted with it."
          : "This search kept no findings — there is nothing else to lose.",
        search.usd_spent > 0
          ? `${usd(search.usd_spent)} also leaves this month's spend total.`
          : "It cost nothing, so nothing changes in this month's spend total.",
      ],
      confirmLabel: "Continue…",
    });
    if (!first) return;

    const second = await ask({
      tone: "clay",
      icon: "warning",
      title: "Really delete it permanently?",
      body: "Second check, on purpose — the row leaves the database for good. There " +
            "is no undo.",
      confirmLabel: "Yes, delete permanently",
      busyLabel: "Deleting",
    });
    if (!second) return;

    setDeleting(true);
    try {
      await api.runs.remove(search.id);
      onDeleted(search.id);
    } catch (e) {
      setDeleteError(e.message);
      setDeleting(false);
    }
  }

  return (
    <div className="search-card">
      {dialog}
      <div className="search-card-head">
        <div>
          <h3>{day} <span className="muted search-card-time">{time}</span></h3>
          <p className="muted small">{trigger}</p>
        </div>
        <div className="search-card-stats">
          <div className="search-stat">
            <strong>{hasBreakdown ? funderCount : "—"}</strong>
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
        <Busy className="iconbtn danger search-card-delete" busy={deleting}
              busyLabel="Deleting" onClick={handleDelete}
              title="Delete this search permanently"
              aria-label="Delete this search permanently">
          <Icon name="bin" size={15} />
        </Busy>
      </div>
      {deleteError && <div className="notice error">{deleteError}</div>}

      {hasBreakdown ? (
        <div className="search-card-boxes">
          <div className="search-box">
            <div className="search-box-head">
              Program cards searched for — {programs.length}
            </div>
            <div className="search-box-chips">
              {programs.map((p) => (
                <span key={p.slug} className="chip on">✓ {p.name}</span>
              ))}
            </div>
          </div>
          <div className="search-box">
            <div className="search-box-head">Funder lists read — {groups.length}</div>
            <div className="search-box-chips">
              {groups.length === 0 ? (
                <span className="muted small">
                  Every funder list came back empty or unreadable this search.
                </span>
              ) : groups.map((g) => (
                <span key={g.label} className="chip on">✓ {g.label} · {g.count}</span>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <p className="muted small search-card-no-breakdown">
          This search ran before Fundworthy started recording which program cards and
          funder lists a search used — a search from here on will show the full
          breakdown.
        </p>
      )}

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
          {findings?.length > 0 && (
            <div className="opps">
              {findings.map((o) => (
                <Finding key={o.id} o={o} maxEffortHours={maxEffortHours} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// A search behind "Show N searches that cost nothing and kept nothing" — collapsed by
// default rather than filtered out server-side. A search that spent $0 and kept 0
// findings is almost always a test run or a broken key, not a real quiet week (a real
// one still triages and scores, so it spends *something*, even a fraction of a cent) —
// but the same disclosure pattern this page already uses for "Show the N findings from
// this search" applies: the app never silently drops a row, it collapses it behind a
// toggle, so a real search that genuinely spent nothing (--no-llm, say) is still one
// click away rather than gone.
function EmptySearches({ searches, month, maxEffortHours, onDeleted }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="search-cards-empty">
      <button type="button" className="text search-toggle" onClick={() => setOpen(!open)}
              aria-expanded={open}>
        {open ? "Hide" : "Show"} the {searches.length} search
        {searches.length === 1 ? "" : "es"} that cost nothing and kept nothing
        <span className={`search-toggle-caret ${open ? "on" : ""}`} aria-hidden="true">
          <Icon name="chevron" size={12} />
        </span>
      </button>
      {open && (
        <div className="search-cards">
          {searches.map((s) => (
            <SearchCard key={s.id} search={s} month={month}
                        maxEffortHours={maxEffortHours} onDeleted={onDeleted} />
          ))}
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

  // A deleted search leaves the list it came from, immediately — the card is not
  // merely collapsed, so leaving it in `data.searches` would make it reappear the
  // moment anything else re-renders.
  function handleDeleted(id) {
    setData((d) => ({ ...d, searches: (d.searches || []).filter((s) => s.id !== id) }));
  }

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
  const realSearches = searches.filter((s) => s.usd_spent > 0 || s.kept_count > 0);
  const emptySearches = searches.filter((s) => !(s.usd_spent > 0 || s.kept_count > 0));

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
            {(data.opportunities || []).length > 0 && (
              <DownloadCsv month={month} searches={searches} />
            )}
          </div>

          {searches.length === 0 ? (
            <p className="muted small">No searches recorded for {monthName(month)}.</p>
          ) : (
            <>
              {realSearches.length > 0 && (
                <div className="search-cards">
                  {realSearches.map((s) => (
                    <SearchCard key={s.id} search={s} month={month}
                                maxEffortHours={data.max_effort_hours}
                                onDeleted={handleDeleted} />
                  ))}
                </div>
              )}
              {emptySearches.length > 0 && (
                <EmptySearches searches={emptySearches} month={month}
                               maxEffortHours={data.max_effort_hours}
                               onDeleted={handleDeleted} />
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
