import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { UNSAFE_NavigationContext, useParams } from "react-router-dom";

/** Width of the element behind the returned ref, tracked with a
 *  ResizeObserver; *fallback* until the first measurement. */
export function useContainerWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry.contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** What clicking a run's mark does: *onSelect* when given, else open the
 *  run page. Outside a router (a bare component test) it does nothing. */
export function useRunSelect(onSelect?: (verstr: string) => void) {
  const { ws, app } = useParams();
  const navigator = useContext(UNSAFE_NavigationContext)?.navigator;
  return useCallback((verstr: string) => {
    if (onSelect) onSelect(verstr);
    else if (navigator && ws && app) {
      navigator.push(`/ws/${ws}/app/${app}/run/${encodeURIComponent(verstr)}`);
    }
  }, [onSelect, navigator, ws, app]);
}

/** The run behind a recharts mark's click payload. */
export function clickedVerstr(entry: unknown): string | null {
  const payload = (entry as { payload?: { verstr?: unknown } } | null)?.payload;
  return typeof payload?.verstr === "string" ? payload.verstr : null;
}
