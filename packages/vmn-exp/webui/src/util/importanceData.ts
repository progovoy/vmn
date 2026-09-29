/** Data prep for the parameter-importance panel. */
import type { ExperimentRow } from "../types";
import { paramValue } from "../util";
import { isFiniteNumber } from "./stats";

export interface ValueMean {
  value: string;
  n: number;
  mean: number;
}

/** The metric's mean per value of a (categorical or bool) param, over the
 *  runs carrying both, ordered by value. */
export function valueMeans(rows: ExperimentRow[], param: string, metric: string): ValueMean[] {
  const acc = new Map<string, { n: number; sum: number }>();
  for (const r of rows) {
    const v = paramValue(r, param);
    const y = r.metrics[metric];
    if (v === undefined || v === null || !isFiniteNumber(y)) continue;
    const key = typeof v === "string" ? v : JSON.stringify(v);
    const cur = acc.get(key) ?? { n: 0, sum: 0 };
    cur.n += 1;
    cur.sum += y;
    acc.set(key, cur);
  }
  return [...acc.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([value, { n, sum }]) => ({ value, n, mean: sum / n }));
}

/** An importance bar's width, as a percentage of the top param's (to 0.01). */
export function barPercent(importance: number, top: number): number {
  return top > 0 ? Math.round((importance / top) * 10_000) / 100 : 0;
}
