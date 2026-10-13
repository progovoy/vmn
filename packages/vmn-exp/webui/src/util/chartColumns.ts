/** Chart rows from `/experiments-columns`: only the keys a chart plots,
 *  over the whole filtered set rather than the pages the table loaded. */
import type { ExperimentColumns, ExperimentRow, RunState } from "../types";
import type { ChartView } from "../hooks/useLeaderboardView";
import { groupColumn } from "./chartGroups";

const PLOTS_PARAMS: ReadonlySet<ChartView> = new Set(["scatter", "parallel", "grouped", "importance"]);
/** The charts that colour each run by its group on a grouped board (plan 22 G7). */
export const COLOURS_BY_GROUP: ReadonlySet<ChartView> = new Set(["bar", "scatter", "parallel"]);

/** The column keys *view* needs; *group*: the board's grouping, if any. */
export function chartKeys(view: ChartView, metricCols: string[], paramCols: string[], group?: string): string[] {
  const keys = metricCols.map((m) => `metrics.${m}`);
  if (PLOTS_PARAMS.has(view)) keys.push(...paramCols.map((p) => `params.${p}`));
  if (view === "grouped") keys.push("branch");
  if (group && COLOURS_BY_GROUP.has(view)) keys.push(groupColumn(group));
  return keys;
}

/** One row per verstr, carrying just the fetched values (missing ones left
 *  out, so charts skip them as they skip a run that never logged a metric). */
export function columnsToRows(data: ExperimentColumns): ExperimentRow[] {
  const entries = Object.entries(data.columns);
  return data.verstrs.map((verstr, i) => {
    const metrics: ExperimentRow["metrics"] = {};
    const params: Record<string, unknown> = {};
    let branch: string | null = null;
    const row: Pick<ExperimentRow, "status" | "name"> = {};
    for (const [key, values] of entries) {
      const v = values[i];
      if (v === null || v === undefined) continue;
      if (key.startsWith("metrics.")) {
        if (typeof v === "number") metrics[key.slice(8)] = v;
      } else if (key.startsWith("params.")) {
        params[key.slice(7)] = v;
      } else if (key === "branch") {
        branch = String(v);
      } else if (key === "status") {
        row.status = v as RunState;
      } else if (key === "name") {
        row.name = String(v);
      }
    }
    return {
      idx: data.idx[i], verstr, code_verstr: verstr, timestamp: null, note: null,
      branch, base_version: null, params, metrics, ...row,
    };
  });
}
