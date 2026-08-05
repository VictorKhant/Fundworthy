import { useEffect, useState } from "react";
import { api } from "../api";

// "We are updating right now." Shown to everyone, signed in or not.
//
// A deploy already waits for in-flight searches and restarts in a couple of seconds, so
// most people would never notice. The ones who do are the ones mid-click, and to them an
// unexplained blink reads as the app breaking rather than as the app being maintained.
//
// Polled rather than pushed. A websocket for one boolean would be a connection to keep
// alive through exactly the restart it exists to report, and the poll is a request that
// returns a two-key object.

export default function MaintenanceBanner() {
  const [state, setState] = useState({ maintenance: false });

  useEffect(() => {
    let live = true;
    const check = async () => {
      const next = await api.maintenance();
      if (live) setState(next);
    };
    check();
    // Every 30s normally. Nothing to be gained by asking harder — a deploy takes
    // minutes, and this is a page decoration, not a control.
    const timer = setInterval(check, 30_000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  if (!state.maintenance) return null;

  return (
    <div className="maintenance" role="status">
      <strong>Update in progress</strong>
      <span>{state.message}</span>
    </div>
  );
}
