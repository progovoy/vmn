/** Which view the experiments page shows (plan 23 W1, §8): `view=jobs|all`,
 *  or a preset of the Outer runs view, `view=live|review` (plan 28 §4.5),
 *  in the URL wins, else the app's last view (localStorage), else Jobs. A
 *  chart view in `view=` (`bar`, `scatter`, ...) belongs to the All runs
 *  board's Charts tab, so it means All runs, like `tab=charts`; `group=parent`
 *  (a bookmark, a saved view) means Jobs, which is that grouping (§3.4). */
import { useCallback, useEffect } from "react";
import { useUrlState } from "../../hooks/useUrlState";
import { BOARD_ONLY_PARAMS, CHART_VIEWS } from "../../hooks/useLeaderboardView";
import { rememberChoice, storedChoice } from "../../util/appChoice";
import { isPreset, type Preset } from "./presets";

export type ExperimentsView = "jobs" | "all" | Preset;

export const VIEW_KEY = "vmn_experiments_view";

const isView = (v: string | null): v is ExperimentsView => v === "jobs" || v === "all" || isPreset(v);

function urlView(p: URLSearchParams): ExperimentsView | null {
  const raw = p.get("view");
  if (p.get("group") === "parent") return "jobs";
  if (isView(raw)) return raw;
  const charts = (CHART_VIEWS as readonly string[]).includes(raw ?? "") || p.get("tab") === "charts";
  return charts ? "all" : null;
}

/** *p* switched to view *next*: the filters and `density` stay, what only
 *  one view's board reads goes. */
export function switchView(p: URLSearchParams, next: ExperimentsView, kind?: string): URLSearchParams {
  for (const k of BOARD_ONLY_PARAMS) p.delete(k);
  p.set("view", next);
  if (kind) p.set("kind", kind);
  return p;
}

/** *search* as the All runs view's (the attention strip's links from Jobs). */
export const allRunsSearch = (search: string) => `?${switchView(new URLSearchParams(search), "all")}`;

export function useExperimentsView(ws: string, app: string) {
  const { params, update } = useUrlState();
  const view = urlView(params) ?? storedChoice(VIEW_KEY, ws, app, isView) ?? "jobs";
  useEffect(() => { rememberChoice(VIEW_KEY, ws, app, view); }, [ws, app, view]);

  /** *kind* (`jobs`/`singles`) picks the Jobs view's side. */
  const setView = useCallback((next: ExperimentsView, kind?: string) =>
    update((p) => { switchView(p, next, kind); }), [update]);

  return { view, setView };
}
