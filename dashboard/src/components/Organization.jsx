import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "./Confirm";
import Icon, { IconButton } from "./Icon";
import Spinner, { Busy } from "./Spinner";
import { api, pacificStamp, usd } from "../api";
import { initials } from "../auth";

// Who else is in this organization, and what it has spent this month.
//
// Two things live together here because they answer the same question — "who can spend
// our money, and how much have they" — and a nonprofit administrator should not have to
// hold that in two places.
//
// On the money: this reports what **Fundworthy** spent, not what is left in the org's
// Anthropic account. That is not a shortcut. Anthropic publishes no credit-balance
// endpoint or header (`anthropic-ratelimit-tokens-remaining` looks like one and is not —
// it is tokens per minute, and it refills), so a "credit remaining" figure could only be
// invented. The number below is one we can stand behind, from our own run log.

// Quick amounts plus a typed figure. The meter reported a limit nobody could change
// without going to look for it, and the one moment somebody wants to change it is the
// moment they are looking at a bar that is nearly full.

function CapEditor({ cap, onSaved }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(String(cap));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { setValue(String(cap)); }, [cap]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.settings.save({ monthly_budget_usd: Number(value) });
      setOpen(false);
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setValue(String(cap));
    setError(null);
    setOpen(false);
  }

  if (!open) {
    return (
      <button className="pill capedit-open" onClick={() => setOpen(true)}>
        <Icon name="chart" size={14} /> Change the monthly limit
      </button>
    );
  }

  return (
    <div className="capedit-panel">
      {/* Said up front rather than as a footnote: this limit is ours, and it is not the
          only one. We can stop spending; we cannot stop Anthropic charging. */}
      <p className="capedit-intro">
        Fundworthy will not spend more than this in a month, whatever else is set. Your
        own limit at Anthropic still applies on top.
      </p>

      {/* Sized for the audience rather than for a round-numbers habit. This panel's own
          copy says a weekly search costs about a dollar, which makes $10 three months of
          use — and $100 a number nobody reading this page should be nudged towards.
          Picking one only stages it — nothing saves until "Save the limit" below, so a
          preset and a typed figure go through the exact same commit step instead of a
          preset saving instantly while a typed number waits for a click. */}
      <div className="capedit-presets">
        {[5, 12, 25, 50].map((amount) => (
          <button key={amount}
                  className={`capedit-preset ${Number(value) === amount ? "on" : ""}`}
                  disabled={busy} onClick={() => setValue(String(amount))}>
            ${amount}
          </button>
        ))}
      </div>

      <div className="capedit-custom">
        <span className="capedit-custom-label">Or type a limit</span>
        <label className="capedit-amount">
          <span className="capedit-currency" aria-hidden="true">$</span>
          <input type="number" min="1" max="500" step="1" value={value}
                 disabled={busy}
                 onChange={(e) => setValue(e.target.value)} />
          <span className="muted small">per month</span>
        </label>
      </div>

      {error && <div className="notice error">{error}</div>}

      <div className="capedit-actions">
        <button className="text" onClick={cancel} disabled={busy}>
          Cancel
        </button>
        <Busy className="pill primary" busy={busy} busyLabel="Saving"
              disabled={!value || Number(value) <= 0} onClick={save}>
          Save the limit
        </Busy>
      </div>
    </div>
  );
}

function Meter({ spend, onChange }) {
  const pct = spend.cap_usd > 0
    ? Math.min(100, Math.round((spend.spent_usd / spend.cap_usd) * 100))
    : 0;
  const tone = spend.over_cap ? "over" : pct >= 80 ? "warn" : "ok";

  return (
    <div className="spend">
      <div className="spend-row">
        <strong>{usd(spend.spent_usd)}</strong>
        <span className="muted">
          of {usd(spend.cap_usd)} this month
          {spend.runs > 0 && ` · ${spend.runs} search${spend.runs === 1 ? "" : "es"}`}
        </span>
      </div>
      <div className={`meter ${tone}`} role="img"
           aria-label={`${usd(spend.spent_usd)} spent of ${usd(spend.cap_usd)}`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <CapEditor cap={spend.cap_usd} onSaved={onChange} />
      {spend.over_cap ? (
        <p className="muted small">
          This month's limit is used up, so searches will not run until next month.
          Raise the limit above if you want to keep going.
        </p>
      ) : (
        <p className="muted small">
          {usd(spend.remaining_usd)} left. Fundworthy stops on its own when this runs
          out — it never spends past the limit you set.
        </p>
      )}
    </div>
  );
}

export default function Organization({ spend, onChange }) {
  const [dialog, ask] = useConfirm();
  const [org, setOrg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Which member row is mid-action, so the spinner lands on the button that was pressed
  // rather than on all of them.
  const [acting, setActing] = useState(null);
  const [copied, setCopied] = useState(null);

  const load = useCallback(async () => {
    try {
      setOrg(await api.org.read());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function invite() {
    setBusy(true);
    setError(null);
    try {
      await api.org.invite();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Both of these are confirmed first and neither is undoable, so the confirmation says
  // what actually happens rather than "are you sure?". Removing somebody cuts them off
  // from the funders, the findings and the API key at once; handing the org over cannot
  // be taken back by the person doing it.
  async function drop(member) {
    const answer = await ask({
      icon: "bin",
      tone: "clay",
      title: `Remove ${member.email} from your organization?`,
      points: [
        "They lose access to your funders, your findings and your saved API key "
          + "immediately.",
        "Next time they sign in they get a fresh, empty organization of their own.",
        "This cannot be undone — you would have to invite them back.",
      ],
      confirmLabel: "Remove them",
    });
    if (!answer) return;
    setActing(`drop:${member.uid}`);
    setError(null);
    try {
      await api.org.removeMember(member.uid);
      await load();
      await onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setActing(null);
    }
  }

  async function handOver(member) {
    const answer = await ask({
      icon: "edit",
      title: `Make ${member.email} the admin of your organization?`,
      points: [
        "They will be able to remove people, including you.",
        "You stay a member and can carry on as normal.",
        "You will not be able to take this back yourself — only they can hand it on "
          + "again.",
      ],
      confirmLabel: "Hand it over",
    });
    if (!answer) return;
    setActing(`give:${member.uid}`);
    setError(null);
    try {
      await api.org.transfer(member.uid);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setActing(null);
    }
  }

  async function revoke(code) {
    try {
      await api.org.revokeInvite(code);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  // navigator.clipboard needs a secure context, which a plain-http VM before certbot is
  // not. Falling back to selecting the text means the button still does something useful
  // rather than failing silently.
  async function copy(code) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(code);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      setError("Could not copy automatically — select the code and copy it by hand.");
    }
  }

  return (
    <section className="card">
      {dialog}
      <h2>Your organization</h2>

      {spend && <Meter spend={spend} onChange={onChange} />}

      {error && <div className="notice error">{error}</div>}

      <h3 className="sub">People</h3>
      {!org ? (
        <p className="loading-line">
          <Spinner label="Loading your organization" />
          Loading…
        </p>
      ) : (
        <ul className="plain">
          {org.members.map((m) => (
            <li key={m.email} className="member">
              {/* Three rows of similar-length addresses at the same weight are three
                  rows nobody tells apart at a glance. The initials are the only thing
                  that distinguishes them before you read a character. */}
              <span className="avatar" aria-hidden="true">{initials(m.email)}</span>
              <span>
                {m.email}
                {m.uid === org.you && <span className="muted small"> (you)</span>}
                {m.is_admin && <span className="chip">Admin</span>}
              </span>
              <span className="muted small">
                last seen {pacificStamp(m.last_seen_at)}
              </span>
              {/* Manage shows for the admin, and never on their own row: removing
                  yourself is what Delete account is for, and handing the org to yourself
                  is not a thing. The server checks all of this again — a hidden button is
                  not a permission.

                  The two are separated by a divider. They sat in a `.row` at `gap: 4px`:
                  "Make admin" and "Remove" four pixels apart, one of which hands somebody
                  your organisation and the other of which cuts them off from it. Make
                  admin keeps its words because it is rare and unfamiliar; Remove is an
                  icon with an aria-label, which is the R10 split. */}
              {org.you_are_admin && m.uid !== org.you && (
                <span className="member-actions">
                  <Busy className="pill" busy={acting === `give:${m.uid}`}
                        busyLabel="Handing over" onClick={() => handOver(m)}>
                    Make admin
                  </Busy>
                  <span className="member-divider" aria-hidden="true" />
                  <Busy className="iconbtn danger" busy={acting === `drop:${m.uid}`}
                        busyLabel="Removing" onClick={() => drop(m)}
                        title={`Remove ${m.email} from your organization`}
                        aria-label={`Remove ${m.email} from your organization`}>
                    <Icon name="bin" size={15} />
                  </Busy>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {org && !org.you_are_admin && (
        <p className="muted small">
          Your organization's admin can add and remove people. Ask them if you need a
          colleague added.
        </p>
      )}

      <h3 className="sub">Invite a colleague</h3>
      <p className="muted small">
        Everyone in your organization shares the same funders, program cards and findings
        — and the same API key. Send someone a code and they join this organization
        instead of starting an empty one of their own.
      </p>

      {org?.invites?.length > 0 && (
        <ul className="plain">
          {org.invites.map((i) => (
            <li key={i.code} className="invite">
              <code className="invite-code">{i.code}</code>
              {/* Copy is a repeated action on a row, which is the R10 rule for an icon.
                  It still says "Copied" for two seconds, because a glyph that does its
                  job silently is a glyph you press again. */}
              <IconButton name="copy"
                          label={copied === i.code ? "Copied" : "Copy the code"}
                          className={copied === i.code ? "on" : ""}
                          onClick={() => copy(i.code)} />
              <span className="muted small">
                expires {pacificStamp(i.expires_at)}
              </span>
              <button className="text danger" onClick={() => revoke(i.code)}>
                Cancel
              </button>
            </li>
          ))}
        </ul>
      )}

      <Busy className="secondary" busy={busy} busyLabel="Creating the code"
            onClick={invite}>
        Create an invitation code
      </Busy>
      <p className="muted small">
        Each code works once and expires in two weeks. Send it however you normally talk
        to your colleague — Fundworthy does not send email on your behalf.
      </p>
    </section>
  );
}
