import { useEffect, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled])", "select:not([disabled])",
  "textarea:not([disabled])", '[tabindex]:not([tabindex="-1"])',
].join(",");

/** Keep Tab and Shift+Tab inside *ref* while mounted: focus moves in on
 *  mount (to *initialFocus*, else the first focusable element) and goes back
 *  to whatever had it before on unmount. */
export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  opts?: { initialFocus?: RefObject<HTMLElement> },
): void {
  const initialFocus = opts?.initialFocus;
  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const previous = document.activeElement as HTMLElement | null;
    // A `tabIndex={-1}` button or input matches FOCUSABLE but is out of the Tab order.
    const focusables = () =>
      [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.tabIndex >= 0);
    (initialFocus?.current ?? focusables()[0] ?? container).focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return e.preventDefault();
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement as HTMLElement | null;
      const outside = !current || !container.contains(current);
      if (e.shiftKey && (outside || current === first)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (outside || current === last)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus();
    };
  }, [ref, initialFocus]);
}
