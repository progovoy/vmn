import { useLayoutEffect, useState, type RefObject } from "react";

/** *ref*'s rendered height (px) while *active*, kept current as it resizes;
 *  null until first measured. */
export function useOffsetHeight(ref: RefObject<HTMLElement>, active: boolean): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    const ro = new ResizeObserver(() => setHeight(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, active]);
  return height;
}
