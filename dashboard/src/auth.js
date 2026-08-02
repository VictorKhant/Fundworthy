// Account chrome — placeholders, deliberately.
//
// There is no auth backend and no per-org data scoping. CLAUDE.md §3 rules out accounts
// for v1, and that is what makes the local-only design honest rather than lazy: the app
// stores an API key, so if it is not reachable from the network there is nothing to
// authenticate. Nothing in this file changes that. It exists so the screens are built and
// reviewable now, and so wiring real accounts later is a change to *this file* plus a
// backend, not a redesign.
//
// Everything below is a stub. When accounts land (UI-ROADMAP.md Phase 6):
//   - AUTH_ENABLED stops being a build flag and becomes "is there a session"
//   - stubOrgs() becomes a fetch of the orgs this account belongs to
//   - Login.jsx's onSubmit stops calling straight through to the app
// HANDOFF.md says what has to change on the server before any of that is safe.

import { orgLabel } from "./api";

// Off by default. `./start.sh` must still open straight onto the dashboard with no
// sign-in wall in front of a local, single-user, localhost-bound app.
//
// The screens stay reachable at /welcome and /signin even with the flag off, so they can
// be reviewed and demoed without rebuilding. What the flag controls is whether the app
// *behaves* as though accounts exist: whether "/" lands on the marketing page, and
// whether the sidebar grows an org switcher and a Sign out.
export const AUTH_ENABLED = import.meta.env.VITE_SHOW_AUTH === "1";

// orgLabel returns a sentence-case fallback ("your organization") because most of its
// uses are mid-sentence. This one is a proper-noun slot, so it gets a capital.
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

export function initials(name) {
  return (name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase() || "?";
}

// The signed-in person. Not read from anywhere — there is nobody to read.
export const STUB_SESSION = { name: "Signed-in user", email: "" };

// One real organisation (whatever this install is set up for) and one invented second
// one, so the switcher demonstrates what it is for. Adding an organisation opens nothing
// yet — there is no second database to switch to.
export function stubOrgs(activeName) {
  return [
    { id: "active", name: titleCase(orgLabel(activeName)), active: true },
    { id: "stub", name: "Harbor Youth Collective", active: false },
  ];
}
