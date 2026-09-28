/** Chart rows from `/experiments-columns`: only the keys a chart plots,
 *  over the whole filtered set rather than the pages the table loaded. */
import type { ExperimentColumns, ExperimentRow } from "../types";
import type { ChartView } from "../hooks/useLeaderboardView";

const PLOTS_PARAMS: ReadonlySet<ChartView> = new Set(["scatter", "parallel", "grouped"]);

/** The column keys *view* needs. */
export function chartKeys(view: ChartView, metricCols: string[], paramCols: string[]): string[] {
  const keys = metricCols.map((m) => `metrics.${m}`);
  if (PLOTS_PARAMS.has(view)) keys.push(...paramCols.map((p) => `params.${p}`));
  if (view === "grouped") keys.push("branch");
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
    for (const [key, values] of entries) {
      const v = values[i];
      if (v === null || v === undefined) continue;
      if (key.startsWith("metrics.")) {
        if (typeof v === "number") metrics[key.slice(8)] = v;
      } else if (key.startsWith("params.")) {
        params[key.slice(7)] = v;
      } else if (key === "branch") {
        branch = String(v);
      }
    }
    return {
      idx: data.idx[i], verstr, code_verstr: verstr, timestamp: null, note: null,
      branch, base_version: null, user_meta: null, params, metrics,
    };
  });
}
