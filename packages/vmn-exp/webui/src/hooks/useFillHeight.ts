/** Keeps a scroll box as tall as the page leaves it (`util/fillHeight.ts`),
 *  re-measured as the page around it or the window changes size. */
import { useLayoutEffect, type RefObject } from "react";
import { fillHeight } from "../util/fillHeight";

/** How far what follows *el* in its own column reaches below it: following
 *  siblings, up to the page, that start under it (not a column beside it). */
function belowIn(el: HTMLElement, page: HTMLElement): number {
  const bottom = el.getBoundingClientRect().bottom;
  let reach = bottom;
  for (let node: HTMLElement | null = el; node && node !== page; node = node.parentElement) {
    for (let sib = node.nextElementSibling; sib; sib = sib.nextElementSibling) {
      const r = sib.getBoundingClientRect();
      if (r.height && r.top >= bottom - 1) reach = Math.max(reach, r.bottom);
    }
  }
  // A few px of slack for sub-pixel rounding, so the page shows no scrollbar.
  return reach - bottom + parseFloat(getComputedStyle(page).paddingBottom || "0") + 4;
}

export function useFillHeight(ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const el = ref.current;
    const page = el?.closest<HTMLElement>(".content");
    if (!el || !page) return;
    const fit = () => {
      const top = el.getBoundingClientRect().top - page.getBoundingClientRect().top + page.scrollTop;
      const max = `${fillHeight({ viewport: page.clientHeight, elTop: top, below: belowIn(el, page) })}px`;
      if (el.style.maxHeight !== max) el.style.maxHeight = max;
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(page);
    if (page.firstElementChild) ro.observe(page.firstElementChild);
    return () => ro.disconnect();
  }, [ref]);
}
