// Account chrome — placeholders, deliberately.
//
// There is no auth backend and no per-org data scoping. CLAUDE.md rules out accounts
// for v1, and that is what makes the local-only design honest rather than lazy: the app
// stores an API key, so if it is not reachable from the network there is nothing to
// authenticate. Nothing in this file changes that. It exists so the screens are built and
// reviewable now, and so wiring real accounts later is a change to *this file* plus a
// backend, not a redesign.
//
// Everything below is a stub. When accounts land (FUTURE.md):
//   - AUTH_ENABLED stops being a build flag and becomes "is there a session"
//   - stubOrgs() becomes a fetch of the orgs this account belongs to
//   - Login.jsx's onSubmit stops calling straight through to the app
// FUTURE.md says what has to change on the server before any of that is safe.

import { orgLabel } from "./api";

// Off by default. `./start.sh` must still open straight onto the dashboard with no
// sign-in wall in front of a local, single-user, localhost-bound app.
//
// The screens stay reachable at /welcome and /signin even with the flag off, so they can
// be reviewed and demoed without rebuilding. What the flag controls is whether the app
// *behaves* as though accounts exist: whether "/" lands on the marketing page, whether
// the sidebar carries a user chip and a Sign out, and whether the org switcher offers a
// second organisation to switch to.
//
// The org switcher itself is NOT gated. Naming the organisation this install belongs to
// is true today — see stubOrgs below.
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

// The organisation this install is set up for, from the org_name setting — that part is
// real. Adding one opens nothing yet: there is no second database to switch to.
//
// The invented second organisation only appears when accounts are notionally on, where
// it demonstrates what the switcher is for. On a real single-org install it would just
// be a stranger's name sitting in their sidebar.
export function stubOrgs(activeName) {
  const orgs = [{ id: "active", name: titleCase(orgLabel(activeName)), active: true }];
  if (AUTH_ENABLED) {
    orgs.push({ id: "stub", name: "Harbor Youth Collective", active: false });
  }
  return orgs;
}
