import { useCallback, useContext } from "react";
import { UNSAFE_NavigationContext, useParams } from "react-router-dom";

/** What clicking a run's mark does: *onSelect* when given, else open the
 *  run page. Outside a router (a bare component test) it only calls *onSelect*. */
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
