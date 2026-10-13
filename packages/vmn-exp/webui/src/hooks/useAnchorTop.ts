/** Tells an open popover where its trigger's bottom is (the *cssVar* style
 *  var, viewport px) on open and on any scroll or resize, so a
 *  viewport-fixed popover (the phone layout) sits right under its trigger. */
import { useLayoutEffect, type RefObject } from "react";

const GAP_PX = 6;

export function useAnchorTop(
  open: boolean, trigger: RefObject<HTMLElement>, popover: RefObject<HTMLElement>, cssVar: string,
) {
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigger.current;
      const p = popover.current;
      if (t && p) p.style.setProperty(cssVar, `${t.getBoundingClientRect().bottom + GAP_PX}px`);
    };
    place();
    // Capture: the page scrolls in its own scroller, whose scroll does not bubble.
    document.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, trigger, popover, cssVar]);
}
