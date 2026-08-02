import { useEffect, useState } from "react";
import { api } from "./api";

// The live state of a search, lifted out of the old RunPanel.
//
// It has to be a hook rather than a component now, because the redesign scatters the
// three things that read it: the "Search again now" button sits in the page header, the
// spend and last-run stamp sit in the status strip, and the streaming log sits under the
// settings panel. They are one piece of state and must never disagree about whether a
// search is running.
//
// A running search stays legible. It polls and streams the agent's own output, because a
// button that goes quiet for four minutes reads as broken, and the honest fix is to show
// the work rather than to fake a progress bar.

export function useRun({ latestRun, running, onChange }) {
  const [live, setLive] = useState({ running, run: latestRun, log: [] });
  const [error, setError] = useState(null);

  // Poll only while something is actually running.
  useEffect(() => {
    if (!live.running && !running) return undefined;
    const id = setInterval(async () => {
      try {
        const next = await api.runs.current();
        setLive(next);
        if (!next.running) {
          clearInterval(id);
          onChange();
        }
      } catch {
        /* the poll failing is not worth showing; the next tick retries */
      }
    }, 1500);
    return () => clearInterval(id);
  }, [live.running, running]);

  // `beforeStart` is how unsaved knob changes get written before the run reads them.
  // Without it, pressing "Search again now" with a changed award floor would run the
  // old floor and silently produce results that contradict what is on screen.
  async function start(beforeStart) {
    setError(null);
    try {
      if (beforeStart) await beforeStart();
      await api.runs.start({});
      setLive({ running: true, run: null, log: ["Starting the search…"] });
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  }

  async function stop() {
    try {
      await api.runs.stop();
    } catch (e) {
      setError(e.message);
    }
  }

  return {
    live,
    run: live.run || latestRun,
    isRunning: live.running || running,
    start,
    stop,
    error,
    setError,
  };
}
