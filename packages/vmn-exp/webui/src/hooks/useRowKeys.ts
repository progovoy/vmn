import { useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

const DOWN = new Set(["j", "ArrowDown"]);
const UP = new Set(["k", "ArrowUp"]);

const isTyping = (el: HTMLElement) => Boolean(el.closest("input, textarea, select"));

/** Keyboard row navigation for a table of `tr[data-row-index]` rows: j/k or
 *  the arrows move a roving tab stop (scrolling it into view), Enter on a row
 *  opens its `data-href`. */
export function useRowKeys(
  container: RefObject<HTMLElement>,
  count: number,
  scrollTo: (index: number) => void,
  open: (href: string) => void,
) {
  const [active, setActive] = useState(0);
  const [focusTick, setFocusTick] = useState(0);
  const wantFocus = useRef(false);
  const current = Math.min(active, Math.max(0, count - 1));

  useLayoutEffect(() => {
    if (!wantFocus.current) return;
    wantFocus.current = false;
    container.current?.querySelector<HTMLElement>(`tr[data-row-index="${current}"]`)?.focus();
  }, [current, focusTick, container]);

  const focusRow = (i: number) => {
    const next = Math.max(0, Math.min(count - 1, i));
    wantFocus.current = true;
    setActive(next);
    setFocusTick((t) => t + 1);
    scrollTo(next);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    if (count === 0 || isTyping(target)) return;
    const row = target.closest<HTMLElement>("tr[data-row-index]");
    const onRow = row === target;
    if (e.key === "Enter" && onRow && row.dataset.href) {
      e.preventDefault();
      open(row.dataset.href);
      return;
    }
    const step = DOWN.has(e.key) ? 1 : UP.has(e.key) ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    // From outside the rows the first key lands on the current tab stop.
    focusRow(row ? Number(row.dataset.rowIndex) + step : current);
  };

  return { active: current, onKeyDown };
}
