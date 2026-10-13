import { useCallback, useEffect, useRef, useState } from "react";
import { useDismiss } from "../hooks/useDismiss";
import "./boardShortcuts.css";

/** The board's keys (hooks/useRowKeys.ts), as the help lists them. */
const SHORTCUTS: readonly (readonly [keys: string[], what: string])[] = [
  [["j", "↓"], "Next row"],
  [["k", "↑"], "Previous row"],
  [["x"], "Select the row"],
  [["shift", "x"], "Select a range"],
  [["Enter", "o"], "Open the run"],
  [["/"], "Focus the filter"],
  [["Esc"], "Leave the rows"],
  [["?"], "This list"],
];

const isTyping = (el: EventTarget | null) =>
  el instanceof Element && Boolean(el.closest('input, textarea, select, [contenteditable="true"]'));

/** The toolbar's `?` button and the popover listing the board's keys; `?`
 *  anywhere on the page but a text field toggles it, Escape closes it. */
export default function BoardShortcuts() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, rootRef, buttonRef);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "?" || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target)) return;
      e.preventDefault();
      setOpen((o) => !o);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (open) panelRef.current?.focus(); }, [open]);

  return (
    <div className="board-shortcuts" ref={rootRef}>
      <button
        ref={buttonRef} className="board-shortcuts-btn" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)"
        aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}
      >
        ?
      </button>
      {open && (
        <div ref={panelRef} className="col-picker board-shortcuts-panel" role="dialog" aria-label="Keyboard shortcuts" tabIndex={-1}>
          <div className="col-picker-title">Keyboard shortcuts</div>
          <dl>
            {SHORTCUTS.map(([keys, what]) => (
              <div key={what} className="board-shortcut">
                <dt>{keys.map((k) => <kbd key={k}>{k}</kbd>)}</dt>
                <dd>{what}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
