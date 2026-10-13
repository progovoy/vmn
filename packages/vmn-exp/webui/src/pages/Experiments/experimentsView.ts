/** Which view the experiments page shows (plan 23 W1, §8): `view=jobs|all`
 *  in the URL wins, else the app's last view (localStorage), else Jobs. A
 *  chart view in `view=` (`bar`, `scatter`, ...) belongs to the All runs
 *  board's Charts tab, so it means All runs, like `tab=charts`; `group=parent`
 *  (a bookmark, a saved view) means Jobs, which is that grouping (§3.4). */
import { useCallback, useEffect } from "react";
import { useUrlState } from "../../hooks/useUrlState";
import { BOARD_ONLY_PARAMS, CHART_VIEWS } from "../../hooks/useLeaderboardView";

export type ExperimentsView = "jobs" | "all";

export const VIEW_KEY = "vmn_experiments_view";

const storageKey = (ws: string, app: string) => `${VIEW_KEY}:${ws}/${app}`;

function stored(ws: string, app: string): ExperimentsView | null {
  try {
    const v = localStorage.getItem(storageKey(ws, app));
    return v === "jobs" || v === "all" ? v : null;
  } catch {
    return null;
  }
}

function remember(ws: string, app: string, v: ExperimentsView) {
  try { localStorage.setItem(storageKey(ws, app), v); } catch { /* not persisted */ }
}

function urlView(p: URLSearchParams): ExperimentsView | null {
  const raw = p.get("view");
  if (p.get("group") === "parent") return "jobs";
  if (raw === "jobs" || raw === "all") return raw;
  const charts = (CHART_VIEWS as readonly string[]).includes(raw ?? "") || p.get("tab") === "charts";
  return charts ? "all" : null;
}

export function useExperimentsView(ws: string, app: string) {
  const { params, update } = useUrlState();
  const view = urlView(params) ?? stored(ws, app) ?? "jobs";
  useEffect(() => { remember(ws, app, view); }, [ws, app, view]);

  const setView = useCallback((next: ExperimentsView) => update((p) => {
    // The filters and `density` stay; what only one view's board reads goes.
    for (const k of BOARD_ONLY_PARAMS) p.delete(k);
    p.set("view", next);
  }), [update]);

  return { view, setView };
}
