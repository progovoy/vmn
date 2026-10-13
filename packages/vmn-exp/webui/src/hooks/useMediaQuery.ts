import { useCallback, useSyncExternalStore } from "react";

/** The board's card layout (plan 20 C8). Matches `leaderboardCards.css`. */
export const NARROW_QUERY = "(max-width: 639px)";
/** A touch screen with no hovering pointer: no keyboard shortcuts to hint. */
export const TOUCH_QUERY = "(hover: none) and (pointer: coarse)";

const listOf = (query: string) =>
  typeof window.matchMedia === "function" ? window.matchMedia(query) : null;

/** Whether *query* matches now, re-rendering when it flips; false where the
 *  browser has no matchMedia. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const list = listOf(query);
    list?.addEventListener("change", onChange);
    return () => list?.removeEventListener("change", onChange);
  }, [query]);
  return useSyncExternalStore(subscribe, () => listOf(query)?.matches ?? false, () => false);
}
