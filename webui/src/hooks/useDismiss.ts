import { useEffect, type RefObject } from "react";

/** Close an open popover on Escape (focus back to *trigger*) or on a mouse
 *  press outside *container*. */
export function useDismiss(
  open: boolean,
  close: () => void,
  container: RefObject<HTMLElement>,
  trigger?: RefObject<HTMLElement>,
) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      trigger?.current?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (!container.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, close, container, trigger]);
}
