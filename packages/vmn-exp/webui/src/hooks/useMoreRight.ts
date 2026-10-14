import { useCallback, useEffect, useState, type RefObject } from "react";

/** The width of the scroller's vertical and the height of its horizontal
 *  scrollbar: the fade over its edge stops before them. */
export interface ScrollGutter { right: number; bottom: number }

const sameGutter = (a: ScrollGutter, b: ScrollGutter) => a.right === b.right && a.bottom === b.bottom;

/** Whether the scroller in *ref* has content past its right edge — the
 *  table's overflow cue — and where its scrollbars sit. Rechecked on
 *  `check()` (call it on scroll), on resize, and whenever *contentWidth*
 *  changes. */
export function useMoreRight(ref: RefObject<HTMLElement>, contentWidth: number) {
  const [more, setMore] = useState(false);
  const [gutter, setGutter] = useState<ScrollGutter>({ right: 0, bottom: 0 });
  const check = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
    const now = {
      right: Math.max(0, el.offsetWidth - el.clientWidth),
      bottom: Math.max(0, el.offsetHeight - el.clientHeight),
    };
    setGutter((was) => (sameGutter(was, now) ? was : now));
  }, [ref]);
  useEffect(() => {
    check();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [check, ref, contentWidth]);
  return { more, gutter, check };
}
