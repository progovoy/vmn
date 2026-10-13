import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

const DOWN = new Set(["j", "ArrowDown"]);
const UP = new Set(["k", "ArrowUp"]);
const ARROWS = new Set(["ArrowDown", "ArrowUp"]);
/** Input types that take typed keys, unlike checkboxes or buttons. */
const TEXT_INPUT = /^(text|search|email|url|tel|password|number|date|datetime-local|month|week|time)$/;
/** Widgets with keys of their own. */
const OWN_KEYS = '[role="menu"], [role="listbox"], [role="dialog"]';
const FILTER_BOX = 'input[aria-label="Filter query"]';

const isTyping = (el: Element) =>
  Boolean(el.closest('textarea, select, [contenteditable="true"]'))
  || (el instanceof HTMLInputElement && TEXT_INPUT.test(el.type));

export interface RowKeyActions {
  /** Open a row's `data-href`. */
  open: (href: string) => void;
  /** Select or unselect the row at *index*; *range* extends from the last toggled row. */
  toggle: (index: number, range: boolean) => void;
  /** Forget the last toggled row. */
  clearAnchor: () => void;
}

/** The board's keys (plan 23 W8) over a table of `tr[data-row-index]` rows,
 *  from anywhere on the page but a text field or a menu: j/k (and the arrows
 *  inside the table) move a roving tab stop, scrolling it into view; on a
 *  row, x toggles its selection, shift+x the range from the last toggled
 *  row, Enter or o opens its `data-href`; / focuses the filter box; Escape
 *  leaves the row and forgets the range anchor. Keys with ctrl, alt or meta
 *  are left alone. */
export function useRowKeys(
  container: RefObject<HTMLElement>,
  count: number,
  scrollTo: (index: number) => void,
  actions: RowKeyActions,
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

  const onKey = (e: KeyboardEvent) => {
    const target = e.target instanceof Element ? e.target : document.body;
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if (isTyping(target) || target.closest(OWN_KEYS)) return;
    const inTable = Boolean(container.current?.contains(target));
    const row = inTable ? target.closest<HTMLElement>("tr[data-row-index]") : null;
    const index = row ? Number(row.dataset.rowIndex) : null;
    const handled = (run: () => void) => { e.preventDefault(); run(); };

    if (e.key === "/") return handled(() => document.querySelector<HTMLElement>(FILTER_BOX)?.focus());
    if (e.key === "Escape") {
      actions.clearAnchor();
      if (row) row.blur();
      return;
    }
    if (count === 0) return;
    if (row && index !== null) {
      // Enter belongs to a link or a checkbox inside the row.
      const open = e.key === "o" || (e.key === "Enter" && row === target);
      if (open && row.dataset.href) return handled(() => actions.open(row.dataset.href!));
      if (e.key === "x" || e.key === "X") return handled(() => actions.toggle(index, e.shiftKey));
    }
    if (e.shiftKey || (ARROWS.has(e.key) && !inTable)) return;
    const step = DOWN.has(e.key) ? 1 : UP.has(e.key) ? -1 : 0;
    // From outside the rows the first key lands on the current tab stop.
    if (step) handled(() => focusRow(index !== null ? index + step : current));
  };
  const latest = useRef(onKey);
  latest.current = onKey;
  useEffect(() => {
    const listener = (e: KeyboardEvent) => latest.current(e);
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);

  return { active: current };
}
