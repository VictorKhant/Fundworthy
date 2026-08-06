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
};

export default function Icon({ name, size = 16 }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      viewBox="0 0 16 16" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth="1.4"
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
