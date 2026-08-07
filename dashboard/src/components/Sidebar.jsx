import { initials } from "../auth";
import Icon from "./Icon";
import OrgSwitcher from "./OrgSwitcher";
import ThemeToggle from "./ThemeToggle";

// The shell's navigation. Three views, no router library — three views never justified a
// dependency someone would have to keep updated, and they still don't.
//
// The user chip and Sign out appear only when there is a real session to end. On a
// localhost install there is nobody signed in, and a "Sign out" that signs you out of
// nothing is a lie told in the furniture.

// Each row carries a glyph. The last pass turned row actions into icons and left this —
// the list a non-technical person scans most often — as four undifferentiated text links,
// which is the one place that went the wrong way. Settings is a toothed COG and not a
// radial burst, so it cannot be mistaken for the sun on the theme control below it; see
// the note at the top of Icon.jsx.
const PAGES = [
  { id: "dashboard", label: "This week", icon: "home" },
  { id: "archive", label: "Past findings", icon: "archive" },
  // Above Settings deliberately. Choosing who to watch is part of using Fundworthy —
  // something an org comes back to as it learns which funders are worth its time — not
  // one-time configuration you set up and forget.
  { id: "discover", label: "Discover funders", icon: "search" },
  { id: "settings", label: "Settings", icon: "cog" },
];

export default function Sidebar({ page, setPage, open, setOpen, orgName, user, onBrand, onSignOut }) {
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
            <span className="sidebar-icon" aria-hidden="true">
              <Icon name={p.icon} width={p.icon === "cog" ? 1.5 : 1.4} />
            </span>
            {p.label}
          </button>
        ))}

        {/* Carries the `margin-top: auto` that used to be on .sidebar-foot, so this and
            the account block below it both sit at the bottom. */}
        <ThemeToggle />

        <div className="sidebar-foot">
          {user ? (
            <div className="userchip">
              <span className="avatar" aria-hidden="true">{initials(user.name)}</span>
              <span className="userchip-text">
                {/* The email, not the display name. On a shared office machine "which
                    account am I in?" is the question this chip has to answer, and two
                    people called Maria have one display name and two addresses. */}
                <span className="userchip-name" title={user.name}>{user.email}</span>
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
