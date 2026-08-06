import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Icon from "./Icon";
import { Busy } from "./Spinner";

// One dialog for every destructive path in the app, replacing window.confirm and
// window.prompt.
//
// The reason is not that the browser's dialogs are ugly. It is that they can only ask
// "are you sure?", and "are you sure?" is the least useful question available — it tells
// somebody that something is irreversible without telling them what it does. `points`
// is the whole point of this component: a short list of what will actually happen,
// written before the person has to decide.
//
// So the copy rule for every caller: say what happens, not how serious it is. "Their
// findings and saved key are deleted; the funders they added stay" beats any number of
// warning triangles.
//
// `tone` is sage for ordinary confirmations and clay for the ones that destroy
// something. Clay rather than red on purpose — these are legitimate actions somebody may
// genuinely want, and frightening them out of one is not this dialog's job. The guard is
// that the consequences are written down, not that the button looks dangerous.

export default function Confirm({
  open,
  tone = "sage",
  icon = null,           // an `Icon` name — see the note above the header below
  title,
  body,
  points = [],
  field = null,          // { label, placeholder, defaultValue, required } — the ex-prompt
  cancelLabel = "Cancel",
  confirmLabel = "Confirm",
  busyLabel,
  onConfirm,
  onCancel,
}) {
  const panel = useRef(null);
  const confirmBtn = useRef(null);
  const returnTo = useRef(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Remember what had focus BEFORE the dialog exists, so Esc can hand it back. Layout
  // effect rather than effect: by the time a passive effect runs the browser may already
  // have moved focus into the new subtree, and we would record the dialog itself.
  useLayoutEffect(() => {
    if (open) {
      returnTo.current = document.activeElement;
      setValue(field?.defaultValue ?? "");
      setError(null);
      setBusy(false);
    }
  }, [open, field?.defaultValue]);

  // Focus lands on the text field when there is one to fill in, and on Confirm when
  // there is not — never on Cancel, which would make Enter mean "no".
  useEffect(() => {
    if (!open) return;
    const target = panel.current?.querySelector("input, textarea") || confirmBtn.current;
    target?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab") return;

      // The focus trap. Without it, Tab walks out of the dialog and into the page
      // behind it, where a screen-reader user is answering a question they can no
      // longer see.
      const focusable = panel.current?.querySelectorAll(
        'button:not(:disabled), [href], input:not(:disabled), textarea, select, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  if (!open) return null;

  function close() {
    onCancel?.();
    // Back to the control that opened this, so keyboard users are not dropped at the
    // top of the document.
    returnTo.current?.focus?.();
  }

  async function confirm() {
    if (field?.required && !value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(field ? value.trim() : undefined);
      returnTo.current?.focus?.();
    } catch (e) {
      // Kept open on failure, with the reason. Closing on an error would leave somebody
      // believing the thing happened.
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div
        className={`dialog ${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        ref={panel}
      >
        {/* A tinted square holding the glyph of the thing about to happen — sage for an
            ordinary confirmation, clay for a destructive one. It is what makes a pause
            dialog and a delete dialog tell themselves apart before a word is read; the
            only other difference between them is the colour of one button at the bottom,
            which is at the far end of the panel from where the eye starts. */}
        <h2 id="dialog-title">
          {icon && (
            <span className="dialog-icon" aria-hidden="true">
              <Icon name={icon} size={19} />
            </span>
          )}
          {title}
        </h2>
        {body && <p className="dialog-body">{body}</p>}

        {points.length > 0 && (
          <ul className="dialog-points">
            {points.map((point, i) => <li key={i}>{point}</li>)}
          </ul>
        )}

        {field && (
          <label className="dialog-field">
            {field.label}
            <input
              value={value}
              placeholder={field.placeholder || ""}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && confirm()}
              autoComplete="off"
            />
          </label>
        )}

        {error && <div className="notice error">{error}</div>}

        <div className="dialog-actions">
          <button className="text" onClick={close} disabled={busy}>{cancelLabel}</button>
          <Busy
            ref={confirmBtn}
            className={tone === "clay" ? "danger" : "primary"}
            busy={busy}
            busyLabel={busyLabel || confirmLabel}
            disabled={Boolean(field?.required) && !value.trim()}
            onClick={confirm}
          >
            {confirmLabel}
          </Busy>
        </div>
      </div>
    </div>
  );
}

// `const [dialog, ask] = useConfirm()` — the awaitable form, which is what the seven
// call sites this replaced actually wanted.
//
// They were all written against `window.confirm`, whose one virtue is that it is a
// function you can await in the middle of a handler. A component is not, so without this
// every caller would hand-roll the same promise-and-ref dance to bridge the two. Render
// `{dialog}` anywhere in the component and call `await ask({...})` wherever the browser
// dialog used to be.
//
// **Resolves to an object or null, never a bare boolean.** The two `window.prompt` cases
// take an optional reason, and "" is a real answer meaning "no reason given" — with a
// boolean it would be indistinguishable from pressing Cancel, and a funder would go on
// the remove list with a reason nobody typed or not go on at all.
//
//    const answer = await ask({ title: …, points: [...] });
//    if (!answer) return;              // cancelled
//    answer.value                      // the typed text, when `field` was given
export function useConfirm() {
  const [config, setConfig] = useState(null);
  const decide = useRef(null);

  const ask = useCallback((cfg) => {
    setConfig(cfg);
    return new Promise((resolve) => { decide.current = resolve; });
  }, []);

  const settle = useCallback((answer) => {
    setConfig(null);
    decide.current?.(answer);
    decide.current = null;
  }, []);

  const dialog = (
    <Confirm
      {...(config || {})}
      open={Boolean(config)}
      onCancel={() => settle(null)}
      onConfirm={(value) => settle({ value: value ?? "" })}
    />
  );

  return [dialog, ask];
}
