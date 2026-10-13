import { useLayoutEffect, useRef, type FocusEvent, type KeyboardEvent } from "react";

const ITEMS = "button, select, input";

/** Left/Right step (and wrap), Home/End jump; null for any other key. */
export function keyTarget(key: string, at: number, n: number): number | null {
  if (key === "ArrowRight") return (at + 1) % n;
  if (key === "ArrowLeft") return (at - 1 + n) % n;
  if (key === "Home") return 0;
  if (key === "End") return n - 1;
  return null;
}

/** An ARIA toolbar's roving focus: one Tab stop (the item last focused), the
 *  arrow keys move between the items. Spread the result on the container. */
export function useRovingToolbar<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const active = useRef(0);
  const items = () => [...(ref.current?.querySelectorAll<HTMLElement>(ITEMS) ?? [])];
  const sync = () => {
    const list = items();
    active.current = Math.min(active.current, Math.max(0, list.length - 1));
    list.forEach((el, i) => { el.tabIndex = i === active.current ? 0 : -1; });
  };
  useLayoutEffect(sync);
  const onFocus = (e: FocusEvent<T>) => {
    const at = items().indexOf(e.target as HTMLElement);
    if (at >= 0 && at !== active.current) { active.current = at; sync(); }
  };
  const onKeyDown = (e: KeyboardEvent<T>) => {
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const next = at < 0 ? null : keyTarget(e.key, at, list.length);
    if (next === null) return;
    e.preventDefault();
    active.current = next;
    sync();
    list[next].focus();
  };
  return { ref, onFocus, onKeyDown };
}
