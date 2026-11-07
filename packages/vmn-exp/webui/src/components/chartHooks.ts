import { useCallback, useContext, useEffect } from "react";
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

/** What the reader picked in a chart, as its pickers name it (bare metric /
 *  param names): "Add to report" saves it. */
export interface ChartChoice { metric?: string; x?: string; y?: string; group?: string }

/** Tells *onChoice* the chart's picks whenever they change. */
export function useChoiceReport(onChoice: ((c: ChartChoice) => void) | undefined, choice: ChartChoice) {
  const { metric, x, y, group } = choice;
  useEffect(() => onChoice?.({ metric, x, y, group }), [onChoice, metric, x, y, group]);
}
