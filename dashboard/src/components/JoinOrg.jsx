import { useState } from "react";
import { api } from "../api";
import { Busy } from "./Spinner";

// The invitation-code form, in the two places it belongs.
//
// It used to be a card of its own above the dashboard, shown only while an account was
// completely untouched (`App.jsx`'s `untouched`). That was wrong twice over: it read as
// a stray box floating above the real page, and gating it on "you have nothing yet"
// meant an established user could never redeem a code at all — the one group most likely
// to be handed one, when two nonprofits merge or somebody changes jobs.
//
// So the form is now a component with no opinion about where it sits:
//
//   Tutorial step 1   before the API-key copy. "Is someone here already using this?" is
//                     the first question, because answering yes makes every later step
//                     unnecessary — you inherit a configured org.
//   Settings          "Join another organization" — a second org, on top of the one
//                      you already have.
//
// **Redeeming ADDS an organization; it does not move, merge, or copy.** It used to
// move — the caller left their old org through the same rules as closing an account,
// which needed a confirm dialog naming what would be lost. `db.redeem_invite` no
// longer touches the home org at all (see its docstring), so there is nothing left to
// confirm and no gate needed before calling this.

export default function JoinOrg({
  cta = "Join my colleague",
  onJoined,
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function join(event) {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) return;
    setError(null);
    setBusy(true);
    try {
      const result = await api.org.join(trimmed);
      setCode("");
      await onJoined(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
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
          {cta}
        </Busy>
      </form>
    </>
  );
}
