/** Serialize a page's current chart view to a `vmn-panel` spec ("Add to report"). */
import { appName } from "../api";
import type { ChartView } from "../hooks/useLeaderboardView";
import type { RowsFilter } from "../queries";
import type { XMode } from "../util/chartData";
import { AUTO_X, NO_X } from "../util/xMetric";
import type { PanelSpec, PinnedRuns, QueryRuns, XAxis } from "./panelSpec";

export const newPanelId = () => "p" + Math.random().toString(36).slice(2, 6);

const base = (appTag: string) => ({ v: 1 as const, id: newPanelId(), app: appName(appTag) });

export interface LeaderboardView {
  app: string;
  view: ChartView;
  filter: RowsFilter;
  /** The runs the chart plots; pinned when the board has no query. */
  verstrs: string[];
  metricCols: string[];
  paramCols: string[];
  defaultMetric?: string | null;
}

function boardRuns({ filter, verstrs }: LeaderboardView): PinnedRuns | QueryRuns {
  if (!filter.query) return { verstrs };
  const runs: QueryRuns = { query: filter.query };
  if (filter.sort) runs.sort = filter.sort;
  if (filter.order) runs.order = filter.order;
  if (filter.archived) runs.archived = true;
  return runs;
}

const paramKeys = (cols: string[]) => cols.map((c) => `params.${c}`);

/** The spec for a leaderboard chart, or null for views no panel type renders. */
export function leaderboardSpec(v: LeaderboardView): PanelSpec | null {
  const common = { ...base(v.app), runs: boardRuns(v) };
  const first = v.metricCols[0] ?? "";
  switch (v.view) {
    case "bar": return { ...common, type: "bar", metric: first };
    case "scatter": {
      // MetricScatter's own default axes.
      const param = paramKeys(v.paramCols)[0];
      return { ...common, type: "scatter", x: v.metricCols[0] ?? param ?? "", y: v.metricCols[1] ?? param ?? first };
    }
    case "parallel": return { ...common, type: "parallel", columns: [...v.metricCols, ...paramKeys(v.paramCols)] };
    case "grouped": return { ...common, type: "grouped", group_by: "branch", metric: first };
    case "importance": return { ...common, type: "importance", metric: v.defaultMetric || first };
    default: return null;
  }
}

export interface OverlayView {
  app: string;
  verstrs: string[];
  keys: string[];
  smoothing: number;
  xMode: XMode;
  x: string;
  logY: boolean;
}

function xAxis(mode: XMode, x: string): XAxis {
  if (mode === "step" && x !== AUTO_X && x !== NO_X) return { mode: "metric", metric: x };
  return { mode };
}

export function overlaySpec(v: OverlayView): PanelSpec {
  return {
    ...base(v.app), type: "curves", runs: { verstrs: v.verstrs }, keys: v.keys,
    x: xAxis(v.xMode, v.x), smoothing: v.smoothing, log_y: v.logY,
  };
}

export function runSpec(app: string, verstr: string): PanelSpec {
  return { ...base(app), type: "run", runs: { verstrs: [verstr] } };
}
