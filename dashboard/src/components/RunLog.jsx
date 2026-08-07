import { useEffect, useRef } from "react";
import Spinner from "./Spinner";

// The agent's own output, streamed. Shown whenever a search is running, regardless of
// whether the settings panel is open — a search that is spending money must be visible
// without the user first having to find the right disclosure to open.
//
// The spinner is not decoration here. A search takes five to ten minutes, and there are
// long stretches — the per-host politeness delay, a slow funder's server — where no new
// line arrives for thirty seconds. A still page and a crashed page look identical, and
// this is the longest wait in the product.

// `log` is `null` while the stored transcript is still being fetched and `[]` once we
// know there isn't one. Those are different sentences: "loading" and "this run kept no
// log" read identically as an empty <pre>, and an empty box is how somebody concludes the
// feature is broken rather than that the data is genuinely absent.
export default function RunLog({ isRunning, log }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);

  const lines = log || [];
  const loading = !isRunning && log === null;

  return (
    <div className="runlog">
      <div className="muted small runlog-head">
        {isRunning && <Spinner label="Searching" size={12} />}
        {isRunning
          ? "Searching — this takes a few minutes. You can leave the page; it keeps going."
          : "What the last search did"}
      </div>
      {loading ? (
        <p className="muted small">Loading the log…</p>
      ) : lines.length === 0 ? (
        <p className="muted small">
          No log was kept for this search. Searches from before this was recorded do not
          have one — the next search will.
        </p>
      ) : (
        <pre ref={ref}>{lines.join("\n")}</pre>
      )}
    </div>
  );
}
