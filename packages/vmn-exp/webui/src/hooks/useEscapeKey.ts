import { useEffect, useRef } from "react";

/** Input types Escape belongs to (typing), unlike checkboxes or buttons. */
const TEXT_INPUT = /^(text|search|email|url|tel|password|number|date|datetime-local|month|week|time)$/;

/** Whether an Escape press is someone else's: an open dialog or popup closes
 *  on it, and a text field may use it while typing. */
function escapeTaken(target: EventTarget | null): boolean {
  if (document.querySelector('[role="dialog"], [aria-haspopup][aria-expanded="true"]')) return true;
  if (!(target instanceof Element)) return false;
  if (target.closest('textarea, select, [contenteditable="true"]')) return true;
  return target instanceof HTMLInputElement && TEXT_INPUT.test(target.type);
}

/** Call *onEscape* on an Escape press anywhere on the page while *active*,
 *  unless a dialog, a popup or a text field takes the key. */
export function useEscapeKey(active: boolean, onEscape: () => void) {
  const latest = useRef(onEscape);
  latest.current = onEscape;
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented && !escapeTaken(e.target)) latest.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active]);
}
