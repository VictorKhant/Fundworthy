import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { authEnabled, initials, orgDisplayName } from "../auth";
import Icon from "./Icon";
import Spinner from "./Spinner";

// Names the organization you are signed in to — and, once there is more than one to
// name, switches between them.
//
// It used to be a label with a caret that did nothing: defensible while a person could
// only ever belong to one org, indefensible the moment a real switcher existed to hold
// more than one, because a chevron next to a name says "you can switch these" whether
// or not you actually can. Joining a colleague's organization by invitation code now
// ADDS a second one to see rather than moving you out of your first (Settings →
// Organization → "Join another organization"), so there is finally something for this
// to switch.
//
// A local install has nobody signed in and exactly one org, so it stays the plain label
// it always was — there is nothing to fetch and nothing to switch.

export default function OrgSwitcher({ orgName, onSwitched, onJoinAnother }) {
  const name = orgDisplayName(orgName);
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState(null);
  const [switching, setSwitching] = useState(null);
  const [error, setError] = useState(null);
  const box = useRef(null);

  const load = useCallback(async () => {
    try {
      setOrgs((await api.orgs.mine()).orgs);
    } catch (e) {
      setError(e.message);
      setOrgs([]);
    }
  }, []);

  // Fetched on open, not on mount — this is chrome in the sidebar of every page, and
  // most sessions never touch it.
  useEffect(() => {
    if (open && orgs === null) load();
  }, [open, orgs, load]);

  useEffect(() => {
    if (!open) return undefined;
    function onDown(e) {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!authEnabled()) {
    return (
      <div className="orgswitch">
        <div className="orgswitch-label static">
          <span className="orgswitch-avatar" aria-hidden="true">{initials(name)[0]}</span>
          <span className="orgswitch-name" title={name}>{name}</span>
        </div>
      </div>
    );
  }

  async function switchTo(org) {
    if (org.is_current || switching) return;
    setSwitching(org.id);
    setError(null);
    try {
      await api.org.switch(org.id);
      setOpen(false);
      setOrgs(null);
      // Everything on screen — funders, programs, findings, spend — belongs to the org
      // that was just left. There is no partial refresh that makes sense here.
      await onSwitched?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSwitching(null);
    }
  }

  return (
    <div className="orgswitch" ref={box}>
      <button
        type="button"
        className="orgswitch-label"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="true"
      >
        <span className="orgswitch-avatar" aria-hidden="true">{initials(name)[0]}</span>
        <span className="orgswitch-name" title={name}>{name}</span>
        <span className="orgswitch-caret" aria-hidden="true">
          <Icon name="chevron" size={12} />
        </span>
      </button>

      {open && (
        <div className="orgswitch-menu" role="menu">
          <div className="orgswitch-heading">Your organizations</div>

          {orgs === null && !error && (
            <p className="loading-line small">
              <Spinner label="Loading your organizations" size={13} />
              Loading…
            </p>
          )}
          {error && <div className="notice error small">{error}</div>}

          {orgs?.map((o) => (
            <button
              key={o.id}
              type="button"
              role="menuitemradio"
              aria-checked={o.is_current}
              className={`orgswitch-item ${o.is_current ? "on" : ""}`}
              onClick={() => switchTo(o)}
              disabled={switching !== null}
            >
              <span className="orgswitch-avatar" aria-hidden="true">
                {initials(o.name)[0]}
              </span>
              <span className="orgswitch-item-text">
                <span className="orgswitch-item-name">{o.name}</span>
                <span className="orgswitch-item-sub muted small">
                  {[
                    o.org_location,
                    `${o.funder_count} funder${o.funder_count === 1 ? "" : "s"}`,
                    o.is_admin ? "Admin" : "Member",
                  ].filter(Boolean).join(" · ")}
                </span>
              </span>
              {switching === o.id ? (
                <Spinner label="Switching" size={14} />
              ) : o.is_current && (
                <span className="orgswitch-check" aria-hidden="true">
                  <Icon name="check" size={14} />
                </span>
              )}
            </button>
          ))}

          <button
            type="button"
            className="orgswitch-item orgswitch-join"
            onClick={() => { setOpen(false); onJoinAnother?.(); }}
          >
            <span className="orgswitch-avatar plus" aria-hidden="true">
              <Icon name="add" size={13} />
            </span>
            Join another organization…
          </button>
        </div>
      )}
    </div>
  );
}
