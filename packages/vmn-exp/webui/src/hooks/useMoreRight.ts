import { useCallback, useEffect, useState, type RefObject } from "react";

/** Whether the scroller in *ref* has content past its right edge — the
 *  table's overflow cue. Rechecked on `check()` (call it on scroll), on
 *  resize, and whenever *contentWidth* changes. */
export function useMoreRight(ref: RefObject<HTMLElement>, contentWidth: number) {
  const [more, setMore] = useState(false);
  const check = useCallback(() => {
    const el = ref.current;
    if (el) setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }, [ref]);
  useEffect(() => {
    check();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [check, ref, contentWidth]);
  return { more, check };
}
