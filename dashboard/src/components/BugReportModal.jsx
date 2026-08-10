import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Busy } from "./Spinner";

// "Report a bug", as a dialog reachable from every page — not a panel buried at the
// bottom of Settings. It used to live there, which meant reporting a problem on This
// week took four clicks through a page that has nothing to do with the problem.
// Anchored next to Sign out instead: it is account-level chrome, not a setting.
//
// Three outcomes, and they read differently on purpose:
//
//   filed: true   a GitHub issue exists. Show the link, clear the form.
//   filed: false  saved on this install, but filing to GitHub itself failed (no token
//                 configured, the repo unreachable). Not the user's problem to be
//                 alarmed by — it is still recorded — so it gets the calm notice.
//   thrown        the request never got a 200 at all: rate-limited, rejected, or the
//                 server unreachable. A real failure, the red notice every other form
//                 in this app uses for one.

function friendlyStamp(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const day = d.toLocaleDateString(undefined, { day: "numeric", month: "long" });
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    .replace(" ", "").toLowerCase();
  return `${day}, ${time}`;
}

function withoutTrailingPeriod(text) {
  return text.replace(/\.+$/, "");
}

export default function BugReportModal({ open, page, lastSearchAt, onClose }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const panel = useRef(null);
  const returnTo = useRef(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement;
    setTitle("");
    setDescription("");
    setResult(null);
    setError(null);
    setBusy(false);
    panel.current?.querySelector("input")?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  if (!open) return null;

  function close() {
    onClose();
    returnTo.current?.focus?.();
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.bugReport.file({
        title: title.trim(),
        description: description.trim(),
        page,
      });
      if (res.filed) {
        setResult({ ok: true, url: res.issue_url, number: res.issue_number });
        setTitle("");
        setDescription("");
      } else {
        setResult({ ok: false, message: res.error || "the request failed" });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const search = friendlyStamp(lastSearchAt);

  return (
    <div className="dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="bug-title" ref={panel}>
        <h2 id="bug-title">Report a bug</h2>
        <p className="dialog-body">
          Tell us what went wrong. It is saved so a real person reads it.
        </p>

        <form onSubmit={submit}>
          <label className="field">
            <span>What happened</span>
            <input
              type="text"
              value={title}
              required
              minLength={3}
              maxLength={200}
              placeholder="One line describing the problem"
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>

          <label className="field">
            <span>Details</span>
            <textarea
              value={description}
              required
              maxLength={5000}
              rows={5}
              placeholder="What did you expect instead? Steps to reproduce help a lot."
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <p className="muted small bugreport-sent-with">
            Sent with it: the screen you were on ({page || "the app"}){search &&
            `, your last search (${search})`}, and nothing else.
          </p>

          {result && result.ok && (
            <div className="notice">
              Filed{result.number ? ` as issue #${result.number}` : ""} —{" "}
              <a href={result.url} target="_blank" rel="noopener noreferrer">
                see it on GitHub ↗
              </a>.
            </div>
          )}
          {result && !result.ok && (
            <div className="notice plain">
              Could not file this automatically: {withoutTrailingPeriod(result.message)}.
              Your text is still here — copy it and open an issue by hand, or try again.
            </div>
          )}
          {error && (
            <div className="notice error">
              Could not file this automatically: {withoutTrailingPeriod(error)}. Your
              text is still here — copy it and open an issue by hand, or try again.
            </div>
          )}

          <div className="dialog-actions">
            <button type="button" className="text" onClick={close} disabled={busy}>
              Cancel
            </button>
            <Busy className="dark" type="submit" busy={busy} busyLabel="Sending">
              Report the bug
            </Busy>
          </div>
        </form>
      </div>
    </div>
  );
}
