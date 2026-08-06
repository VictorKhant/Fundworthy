// Everything that waits, waiting visibly.
//
// The app is full of operations that take real time and used to show nothing but a
// changed word on a button: "Read this page for me" becomes "Reading the page…" and then
// sits perfectly still for eight seconds while Sonnet reads a website. Static text is
// indistinguishable from a frozen page, and the nonprofit administrator this is built for
// does not have a mental model of "the request is in flight" to fall back on. So anything
// that can take more than a moment moves while it does.
//
// Two exports, because there are two shapes of wait:
//
//   <Spinner/>   the mark itself, for putting next to your own copy
//   <Busy>       a button that grows a spinner and disables itself while busy — the
//                common case, and worth a component so every button does it identically
//
// It is a bordered circle with one transparent edge, spun by CSS. No SVG, no library, no
// image request: it has to appear instantly, and a spinner that arrives after the thing
// it is covering for has finished is worse than none.
//
// `aria-live` and the visually-hidden label matter here more than usual. A screen reader
// gets nothing at all from a rotating border, so the state is announced in words.

export default function Spinner({ label = "Working", size }) {
  return (
    <span
      className="spinner"
      style={size ? { width: size, height: size } : undefined}
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">{label}…</span>
    </span>
  );
}

// A button that knows how to wait.
//
// `busy` drives all three of the things that have to stay in step — the spinner, the
// label, and being disabled — because getting two of the three right is how you end up
// with a button that looks busy and can still be pressed four more times. Each of those
// presses was a Sonnet call.
export function Busy({ busy, children, busyLabel, disabled, ...rest }) {
  return (
    <button {...rest} disabled={busy || disabled} aria-busy={busy || undefined}>
      {busy && <Spinner label={busyLabel || "Working"} size={13} />}
      {busy ? busyLabel || children : children}
    </button>
  );
}
