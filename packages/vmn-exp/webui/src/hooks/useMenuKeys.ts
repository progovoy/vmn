/** The menu pattern (WAI-ARIA menu button): the first item takes focus when
 *  the menu opens; arrows wrap, Home/End jump, Tab leaves (and closes). */
import { useCallback, useEffect, type KeyboardEvent, type RefObject } from "react";

const ITEM = '[role="menuitem"]';

/** Returns the menu element's onKeyDown. *menu* holds the menuitems. */
export function useMenuKeys(open: boolean, menu: RefObject<HTMLElement>, close: () => void) {
  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLElement>(ITEM)?.focus();
  }, [open, menu]);

  return useCallback((e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Tab") return close();
    const items = [...e.currentTarget.querySelectorAll<HTMLElement>(ITEM)];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const to = ({ ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 } as Record<string, number>)[e.key];
    if (to === undefined) return;
    e.preventDefault();
    items[(to + items.length) % items.length]?.focus();
  }, [close]);
}
