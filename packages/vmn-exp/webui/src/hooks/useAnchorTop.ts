/** Tells an open popover where its trigger's bottom is (the *cssVar* style
 *  var, viewport px) on open and on any scroll or resize, so a
 *  viewport-fixed popover (the phone layout) sits right under its trigger;
 *  *leftVar* also gets the trigger's left edge (a popover fixed at every width). */
import { useLayoutEffect, type RefObject } from "react";

const GAP_PX = 6;

export function useAnchorTop(
  open: boolean, trigger: RefObject<HTMLElement>, popover: RefObject<HTMLElement>, cssVar: string, leftVar?: string,
) {
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigger.current;
      const p = popover.current;
      if (!t || !p) return;
      const rect = t.getBoundingClientRect();
      p.style.setProperty(cssVar, `${rect.bottom + GAP_PX}px`);
      if (leftVar) p.style.setProperty(leftVar, `${rect.left}px`);
    };
    place();
    // Capture: the page scrolls in its own scroller, whose scroll does not bubble.
    document.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, trigger, popover, cssVar, leftVar]);
}
