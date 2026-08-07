// One 16px stroke set, inline.
//
// No icon font and no icon package: `styles.css` notes there is no image asset anywhere
// in this app, and that is worth keeping true. An icon font is a network request that
// can fail and leave a row of boxes; a package is a dependency somebody has to keep
// current for eight glyphs.
//
// **Every icon-only control needs a `title` AND an `aria-label`.** They do different
// jobs — the tooltip is for the person who cannot guess the glyph, the label is for the
// person who cannot see it — and an icon button with neither is a button that means
// nothing to anybody. `<IconButton>` below makes that hard to forget.
//
// The rule for what becomes an icon, from R10: repeated actions on a row (edit, block,
// delete, copy, download) become icons; anything **rare, destructive or unfamiliar**
// keeps its words — "Make admin", "Share mine", "Search again now", "Put back". A person
// with no technical background should never have to learn a glyph to do something they
// do once.

// Three of these are the same first draft — "a circle with rays or spokes" — and drawn
// that way any two are indistinguishable at 14–16px. They mean completely different
// things, so they get completely different silhouettes and they all live here, where a
// fourth caller cannot reinvent one of them:
//
//   sun      (ThemeToggle)  a disc with eight straight rays  → the light theme
//   cog      (Sidebar nav)  a ring of trapezoidal teeth      → the Settings page
//   sliders  (StatusStrip)  two rails, two offset knobs      → the four search numbers
//
// Sliders rather than a second gear for "Adjust search settings" because that button
// opens four numeric values you tune, and it sits two panels away from the Settings nav
// item. Two gears on one screen meaning different destinations is the confusion this
// split exists to prevent.
const PATHS = {
  edit: <path d="M11.2 2.4a1.4 1.4 0 0 1 2 2L5.8 11.8l-2.7.7.7-2.7z" />,
  block: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M4 12 12 4" />
    </>
  ),
  bin: (
    <>
      <path d="M2.8 4.3h10.4M6.4 4.3V3a.7.7 0 0 1 .7-.7h1.8a.7.7 0 0 1 .7.7v1.3" />
      <path d="M12.1 4.3l-.5 8.4a1 1 0 0 1-1 .95H5.4a1 1 0 0 1-1-.95l-.5-8.4" />
      <path d="M6.6 6.8v4M9.4 6.8v4" />
    </>
  ),
  pause: <path d="M6 3.2v9.6M10 3.2v9.6" />,
  copy: (
    <>
      <rect x="5.6" y="5.6" width="7.6" height="7.6" rx="1.4" />
      <path d="M10.4 5.6V4.2a1.4 1.4 0 0 0-1.4-1.4H4.2a1.4 1.4 0 0 0-1.4 1.4v4.8a1.4 1.4 0 0 0 1.4 1.4h1.4" />
    </>
  ),
  download: (
    <>
      <path d="M8 2.6v7.2" />
      <path d="M5.2 7.2 8 10l2.8-2.8" />
      <path d="M2.8 11.6v1a1 1 0 0 0 1 1h8.4a1 1 0 0 0 1-1v-1" />
    </>
  ),
  search: (
    <>
      <circle cx="7.2" cy="7.2" r="4.4" />
      <path d="m10.5 10.5 2.7 2.7" />
    </>
  ),
  add: <path d="M8 3.2v9.6M3.2 8h9.6" />,
  check: <path d="M3.2 8.4 6.4 11.6 12.8 4.8" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,

  // The four nav glyphs. "Discover funders" reuses `search` above rather than carrying a
  // second magnifier of its own — see the note at the top of this block.
  home: <path d="M2.5 8.5 8 3l5.5 5.5M4 7.8V13h8V7.8" />,
  archive: <path d="M2.5 5.5h11v7.5h-11zM2.5 5.5 4 3h8l1.5 2.5M6.5 8.5h3" />,
  cog: (
    <>
      <path d="M14.4 6.4 14.4 9.6 12.9 9.2 12.3 10.6 13.7 11.4 11.4 13.7 10.6 12.3 9.2 12.9 9.6 14.4 6.4 14.4 6.8 12.9 5.4 12.3 4.6 13.7 2.3 11.4 3.7 10.6 3.2 9.2 1.6 9.6 1.6 6.4 3.2 6.8 3.7 5.4 2.3 4.6 4.6 2.3 5.4 3.7 6.8 3.2 6.4 1.6 9.6 1.6 9.2 3.2 10.6 3.7 11.4 2.3 13.7 4.6 12.3 5.4 12.9 6.8Z" />
      <path d="M8 5.7a2.3 2.3 0 1 0 0 4.6 2.3 2.3 0 0 0 0-4.6" />
    </>
  ),
  sliders: (
    <>
      <path d="M2.5 4.5h4M9.5 4.5h4M2.5 11.5h1.5M7 11.5h6.5" />
      <circle cx="8" cy="4.5" r="1.7" />
      <circle cx="5.5" cy="11.5" r="1.7" />
    </>
  ),

  terminal: <path d="M4 5.5 6.5 8 4 10.5M8.5 11h4" />,
  chevron: <path d="M6.2 3.5 10.7 8l-4.5 4.5" />,
  warning: <path d="M8 2.8 14 13.2H2zM8 6.6v3.1M8 11.5v.05" />,
  pin: (
    <>
      <path d="M8 2.2a4.2 4.2 0 0 1 4.2 4.2c0 3.1-4.2 7.4-4.2 7.4S3.8 9.5 3.8 6.4A4.2 4.2 0 0 1 8 2.2Z" />
      <circle cx="8" cy="6.3" r="1.6" />
    </>
  ),
  basket: (
    <>
      <path d="M2.4 6.2h11.2l-1.1 6.1a1 1 0 0 1-1 .8H4.5a1 1 0 0 1-1-.8Z" />
      <path d="M5.6 6.2 8 2.6l2.4 3.6" />
    </>
  ),
  upload: (
    <>
      <path d="M8 12.4V3.6" />
      <path d="M5 6.6 8 3.6l3 3" />
      <path d="M3 12.6v.4a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-.4" />
    </>
  ),
  flag: <path d="M4 13.4V2.9m0 .6h7.6l-1.6 2.7 1.6 2.7H4" />,
};

export default function Icon({ name, size = 16, width = 1.4 }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      viewBox="0 0 16 16" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth={width}
      strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
    >
      {path}
    </svg>
  );
}

// An icon-only button that cannot be built without a label.
//
// `label` is required and becomes both the tooltip and the accessible name, so the two
// can never disagree and neither can be forgotten. That is the whole reason this exists
// rather than everyone hand-rolling `<button><Icon/></button>`.
export function IconButton({ name, label, className = "", ...rest }) {
  return (
    <button
      type="button"
      className={`iconbtn ${className}`.trim()}
      title={label}
      aria-label={label}
      {...rest}
    >
      <Icon name={name} />
    </button>
  );
}
