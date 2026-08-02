import { useEffect, useRef } from "react";

// The agent's own output, streamed. Shown whenever a search is running, regardless of
// whether the settings panel is open — a search that is spending money must be visible
// without Mauri first having to find the right disclosure to open.

export default function RunLog({ isRunning, log }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);

  return (
    <div className="runlog">
      <div className="muted small">{isRunning ? "Searching…" : "What the last search did"}</div>
      <pre ref={ref}>{(log || []).join("\n")}</pre>
    </div>
  );
}
