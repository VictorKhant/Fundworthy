import { initials, orgDisplayName } from "../auth";

// Names the organization you are signed in to. A label, not a switcher.
//
// It used to be a dropdown with a caret and an "+ Add an organization" item, both inert.
// That was defensible while orgs did not exist — the control was holding a layout
// position for a backend that was coming. It stopped being defensible the moment orgs
// became real: a chevron next to a name now says "you can switch between these", and a
// person who belongs to exactly one organization would click it, find nothing, and
// reasonably conclude the app is broken.
//
// One person belongs to one organization. Colleagues join yours by invitation code
// (Settings → Your organization), which is a different action in a different place, and
// nothing here should imply otherwise. If a person ever belongs to several, this becomes
// a real switcher — but then it will switch something.

export default function OrgSwitcher({ orgName }) {
  const name = orgDisplayName(orgName);

  return (
    <div className="orgswitch">
      <div className="orgswitch-label static">
        <span className="orgswitch-avatar" aria-hidden="true">{initials(name)[0]}</span>
        <span className="orgswitch-name" title={name}>{name}</span>
      </div>
    </div>
  );
}
