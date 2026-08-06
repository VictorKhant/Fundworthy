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

export default function RunLog({ isRunning, log }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);

  return (
    <div className="runlog">
      <div className="muted small runlog-head">
        {isRunning && <Spinner label="Searching" size={12} />}
        {isRunning
          ? "Searching — this takes a few minutes. You can leave the page; it keeps going."
          : "What the last search did"}
      </div>
      <pre ref={ref}>{(log || []).join("\n")}</pre>
    </div>
  );
}
