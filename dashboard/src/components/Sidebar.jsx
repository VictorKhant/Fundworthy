import { AUTH_ENABLED, initials, STUB_SESSION } from "../auth";
import OrgSwitcher from "./OrgSwitcher";

// The shell's navigation. Three views, no router library — three views never justified a
// dependency someone would have to keep updated, and they still don't.
//
// The account chrome (org switcher, user chip, Sign out) only appears behind
// VITE_SHOW_AUTH. Without it this is a local single-user app and a "Sign out" that signs
// you out of nothing is a lie told in the furniture.

const PAGES = [
  { id: "dashboard", label: "This week" },
  { id: "archive", label: "Past findings" },
  { id: "settings", label: "Settings" },
];

export default function Sidebar({ page, setPage, open, setOpen, orgName, onBrand, onSignOut }) {
  return (
    <>
      <button
        className="sidebar-toggle"
        onClick={() => setOpen(!open)}
        aria-label={open ? "Hide the menu" : "Show the menu"}
        aria-expanded={open}
      >
        ☰
      </button>

      <nav className={`sidebar ${open ? "open" : ""}`} aria-label="Sections">
        {/* The wordmark goes home, the way a wordmark does everywhere else. A real
            <button> rather than an <a href="/welcome">: navigation here is a state change
            inside the app, and a hard link would drop the whole SPA and refetch it. */}
        <button className="brandmark" onClick={onBrand} title="Go to the Fundworthy home page">
          Fundworthy
          <span className="brand-dot" aria-hidden="true" />
        </button>

        {/* Always visible, unlike the rest of the account chrome. Naming who this
            install belongs to is true right now — it comes from the org_name setting —
            and it is the one piece that is not waiting on accounts to mean something.
            What it cannot yet do (switch, add) says so in a tooltip. */}
        <OrgSwitcher orgName={orgName} />

        {PAGES.map((p) => (
          <button
            key={p.id}
            className={`sidebar-link ${page === p.id ? "current" : ""}`}
            onClick={() => {
              setPage(p.id);
              if (window.innerWidth < 900) setOpen(false);
            }}
            aria-current={page === p.id ? "page" : undefined}
          >
            {p.label}
          </button>
        ))}

        <div className="sidebar-foot">
          {AUTH_ENABLED ? (
            <div className="userchip">
              <span className="avatar" aria-hidden="true">{initials(STUB_SESSION.name)}</span>
              <span className="userchip-text">
                <span className="userchip-name">{STUB_SESSION.name}</span>
                <button className="text userchip-out" onClick={onSignOut}>
                  Sign out
                </button>
              </span>
            </div>
          ) : (
            <div className="muted small">
              Runs on this computer.
              <br />
              Nothing is public.
            </div>
          )}
        </div>
      </nav>

      {open && <div className="scrim" onClick={() => setOpen(false)} />}
    </>
  );
}
