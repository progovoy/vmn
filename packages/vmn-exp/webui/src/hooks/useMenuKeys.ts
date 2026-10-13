/** The menu pattern (WAI-ARIA menu button): the checked radio item, else the
 *  first item, takes focus when the menu opens; arrows wrap, Home/End jump, Tab leaves (and closes). */
import { useCallback, useEffect, type KeyboardEvent, type RefObject } from "react";

const ITEM = '[role="menuitem"], [role="menuitemradio"]';
const CHECKED = '[role="menuitemradio"][aria-checked="true"]';

/** Where each key moves focus from item *at* of *n*; undefined = not a menu key. */
const target = (key: string, at: number, n: number): number | undefined =>
  ({ ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: n - 1 } as Record<string, number>)[key];

/** Returns the menu element's onKeyDown. *menu* holds the menuitems. */
export function useMenuKeys(open: boolean, menu: RefObject<HTMLElement>, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const at = menu.current?.querySelector<HTMLElement>(CHECKED) ?? menu.current?.querySelector<HTMLElement>(ITEM);
    at?.focus();
  }, [open, menu]);

  return useCallback((e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Tab") return close();
    const items = [...e.currentTarget.querySelectorAll<HTMLElement>(ITEM)];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const to = target(e.key, at, items.length);
    if (to === undefined) return;
    e.preventDefault();
    items[(to + items.length) % items.length]?.focus();
  }, [close]);
}
