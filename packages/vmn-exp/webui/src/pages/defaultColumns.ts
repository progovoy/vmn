/** Which metric and param columns the leaderboard shows before the user
 *  picks any (plan 20 D11): the declared-goal metrics, and a few params
 *  whose values vary across the loaded rows. */
import type { ExperimentRow, MetricsSchema } from "../types";
import { rowParams } from "../util";

/** The most params shown by default; the rest come from the column picker. */
export const MAX_DEFAULT_PARAMS = 6;

/** Param column width (px) the budget counts in (see `defaultWidth`). */
const PARAM_WIDTH = 120;

/** *metricCols* whose goal the schema declares (never one guessed from a name). */
export function goalMetrics(metricCols: readonly string[], schema: MetricsSchema | null): string[] {
  return metricCols.filter((m) => {
    const goal = schema?.[m]?.goal;
    return goal === "min" || goal === "max";
  });
}

/** *paramCols* that take more than one value across *rows*, the ones most
 *  rows carry first. With a single row there is nothing to compare, so
 *  every param counts. */
export function variedParams(rows: readonly ExperimentRow[], paramCols: readonly string[]): string[] {
  if (rows.length < 2) return [...paramCols];
  const seen = new Map<string, Set<string>>();
  const carried = new Map<string, number>();
  for (const r of rows) {
    for (const [k, v] of Object.entries(rowParams(r))) {
      if (v == null) continue;
      if (!seen.has(k)) seen.set(k, new Set());
      seen.get(k)!.add(JSON.stringify(v));
      carried.set(k, (carried.get(k) ?? 0) + 1);
    }
  }
  return paramCols
    .filter((k) => (seen.get(k)?.size ?? 0) > 1)
    .map((k, i) => ({ k, i, n: carried.get(k) ?? 0 }))
    .sort((a, b) => b.n - a.n || a.i - b.i)
    .map((e) => e.k);
}

/** How many default params fit in *fill* px beside *taken* px of other
 *  columns; the most allowed while the width is not known (0). */
export function paramBudget(fill: number, taken: number): number {
  if (fill <= 0) return MAX_DEFAULT_PARAMS;
  return Math.max(0, Math.min(MAX_DEFAULT_PARAMS, Math.floor((fill - taken) / PARAM_WIDTH)));
}
