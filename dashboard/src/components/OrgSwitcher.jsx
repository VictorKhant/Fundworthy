import { useEffect, useRef, useState } from "react";
import { initials, orgsFor } from "../auth";

// The org switcher. Names the organisation this install belongs to, which is true;
// switching and "+ Add an organization" do nothing yet, because there is no second
// database to switch to (see auth.js, and FUTURE.md §4 for what would have to exist).
//
// It is here rather than waiting for the backend because it settles a layout question —
// where the current organisation's name lives — that everything else in the sidebar has
// to be positioned around.

export default function OrgSwitcher({ orgName }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const orgs = orgsFor(orgName);
  const active = orgs.find((o) => o.active) || orgs[0];

  // Outside click closes. A dropdown you can only dismiss by re-clicking the control
  // that opened it is the kind of thing that reads as broken to someone who has never
  // been told it is a dropdown.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="orgswitch" ref={ref}>
      <button className="orgswitch-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="orgswitch-label">
          <span className="orgswitch-avatar" aria-hidden="true">{initials(active.name)[0]}</span>
          <span className="orgswitch-name">{active.name}</span>
        </span>
        <span className="orgswitch-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="orgswitch-menu">
          {orgs.map((o) => (
            <button
              key={o.id}
              className={`orgswitch-item ${o.active ? "current" : ""}`}
              onClick={() => setOpen(false)}
              title={o.active ? undefined : "Switching organizations needs accounts — not built yet"}
            >
              <span className={`orgswitch-avatar ${o.active ? "" : "alt"}`} aria-hidden="true">
                {initials(o.name)[0]}
              </span>
              {o.name}
            </button>
          ))}
          <div className="orgswitch-rule" />
          <button
            className="orgswitch-item add"
            onClick={() => setOpen(false)}
            title="Needs accounts — not built yet"
          >
            + Add an organization
          </button>
        </div>
      )}
    </div>
  );
}
