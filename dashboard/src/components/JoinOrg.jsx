import { useState } from "react";
import { api } from "../api";
import { Busy } from "./Spinner";

// "Are you joining a colleague, or starting fresh?" — asked once, right after a first
// sign-in, before the person has invested anything in an empty dashboard.
//
// The order matters. Ask afterwards and the answer is worthless: they have already been
// given an organization, possibly typed their programs into it, and "join my colleague"
// now means merging two sets of data rather than picking a door. Ask first and it is a
// two-way choice with nothing at stake.
//
// Redeeming a code MOVES this person into that org. It does not merge, and it does not
// copy — which is why this is only offered while their own org is still empty.

export default function JoinOrg({ onJoined, onSkip }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function join(event) {
    event.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.org.join(code.trim());
      await onJoined();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card welcome">
      <h2>Welcome to Fundworthy</h2>
      <p>
        Is someone at your organization already using Fundworthy? If they sent you an
        invitation code, enter it here and you will share their funders, programs and
        findings.
      </p>

      {error && <div className="notice error">{error}</div>}

      <form onSubmit={join} className="join">
        <label htmlFor="invite-code">Invitation code</label>
        <input
          id="invite-code"
          value={code}
          // Uppercased as they type: the code is generated uppercase and read off a
          // screen or a sticky note, and being told "not valid" over letter case would
          // be a miserable first thirty seconds with the product.
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="ABCD-EFGH-JKMN"
          autoComplete="off"
          spellCheck="false"
        />
        <Busy type="submit" busy={busy} busyLabel="Joining" disabled={!code.trim()}>
          Join my colleague
        </Busy>
      </form>

      <p className="muted small">
        No code? Start your own organization instead — you can invite colleagues later
        from the Settings page.
      </p>
      <button className="text" onClick={onSkip}>
        I'm setting this up for the first time
      </button>
    </section>
  );
}
