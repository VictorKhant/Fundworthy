import { useState } from "react";
import { api, dayAndTime } from "../api";
import Icon from "./Icon";
import { Busy } from "./Spinner";

// "Download spreadsheet", on both This week and Past findings.
//
// This was an <a download> pointing straight at the CSV endpoint, which was the better
// shape — the browser saved the file natively, with no JavaScript in the path and no
// spinner state to get stuck in. Sign-in took that away: a link navigation sends cookies
// and nothing else, and the API authenticates with a bearer token, so the link would
// simply 401. api.downloadCsv fetches it with the header and hands the browser a blob
// under the same filename.
//
// The state this component exists to own is the failure. A download that silently does
// nothing is the worst version of this button, so a failed one says so in place.
//
// `searches` is new, and optional. This week never passes it — there is only ever one
// search worth exporting there — so it still downloads on the first click exactly as it
// always did. Past findings passes the month's whole list, and this component opens an
// inline picker instead of downloading immediately whenever there is a real choice to
// make: "Aug 7 10am" and "Aug 6 1pm" together, everything else from the month left out.

export default function DownloadCsv({ month, searches }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [picking, setPicking] = useState(false);
  const [checked, setChecked] = useState(() => new Set());

  // Only a search that actually kept something is worth choosing between — one that
  // kept nothing would just be an empty row in the picker with nothing to add to the
  // file either way.
  const pickable = (searches || []).filter((s) => s.kept_count > 0);

  async function download(runIds) {
    setBusy(true);
    setError(null);
    try {
      await api.downloadCsv(month, runIds);
      setPicking(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function openPicker() {
    // Every search pre-checked — unchecking narrows the file; leaving them all checked
    // downloads exactly what the old one-click button always produced.
    setChecked(new Set(pickable.map((s) => s.id)));
    setError(null);
    setPicking(true);
  }

  function toggle(id) {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  // Nothing to choose between: no searches passed in at all (This week), or the month
  // has one search or none worth exporting. Falls back to the original one-click
  // download rather than offering a picker with a single, forced option in it.
  if (pickable.length < 2) {
    return (
      <>
        <Busy className="download-csv" busy={busy} busyLabel="Preparing"
              onClick={() => download(null)}>
          <Icon name="download" size={15} />
          Download spreadsheet
        </Busy>
        {error && <span className="muted small">{error}</span>}
      </>
    );
  }

  return (
    <div className="download-csv-wrap">
      <Busy className="download-csv" busy={busy} busyLabel="Preparing" onClick={openPicker}>
        <Icon name="download" size={15} />
        Download spreadsheet
      </Busy>
      {error && <span className="muted small">{error}</span>}

      {picking && (
        <div className="download-picker">
          <p className="muted small">
            Every search is checked — the same file this button always produced. Uncheck
            any search to leave it out.
          </p>
          <ul className="plain download-picker-list">
            {pickable.map((s) => {
              const { day, time } = dayAndTime(s.started_at);
              return (
                <li key={s.id}>
                  <label className="download-picker-row">
                    <input type="checkbox" checked={checked.has(s.id)}
                           onChange={() => toggle(s.id)} />
                    {day} <span className="muted">{time}</span> — {s.kept_count} finding
                    {s.kept_count === 1 ? "" : "s"}
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="dialog-actions">
            <button className="text" onClick={() => setPicking(false)} disabled={busy}>
              Cancel
            </button>
            <Busy className="primary" busy={busy} busyLabel="Preparing"
                  disabled={checked.size === 0}
                  onClick={() => download([...checked])}>
              Download {checked.size === pickable.length ? "all" : checked.size} search
              {checked.size === 1 ? "" : "es"}
            </Busy>
          </div>
        </div>
      )}
    </div>
  );
}
