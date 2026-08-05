import { useState } from "react";
import { api } from "../api";

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

export default function DownloadCsv({ month }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function download() {
    setBusy(true);
    setError(null);
    try {
      await api.downloadCsv(month);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button onClick={download} disabled={busy}>
        {busy ? "Preparing…" : "Download spreadsheet"}
      </button>
      {error && <span className="muted small">{error}</span>}
    </>
  );
}
