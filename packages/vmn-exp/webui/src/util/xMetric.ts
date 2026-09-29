/** Charting a metric against another metric (`define_metric(step_metric=)`).
 *
 *  The join itself happens server-side (`x=` on the series endpoints), so it
 *  survives downsampling: a joined point carries `x`, the x metric's value at
 *  the same step. These pure helpers decide which charts need a join and pick
 *  the points each chart draws. */
import type { SeriesPoint } from "../types";
import { splitSysMetrics, type XMode } from "./chartData";

/** Each metric's declared step metric, if any. */
export const AUTO_X = "auto";
/** Plain step axis, declarations ignored. */
export const NO_X = "none";

type Series = Record<string, SeriesPoint[]>;
export type XMap = Record<string, string>;

/** The x metric *metric*'s chart uses, or null for the plain x mode. */
export function chartXMetric(
  mode: XMode, choice: string, metric: string, declared: XMap | undefined,
): string | null {
  if (mode !== "step" || choice === NO_X) return null;
  const x = choice === AUTO_X ? declared?.[metric] : choice;
  return x && x !== metric ? x : null;
}

/** `{metric: x metric}` for the *metrics* whose charts need a join. */
export function xMetricMap(
  metrics: string[], mode: XMode, choice: string, declared: XMap | undefined,
): XMap {
  const map: XMap = {};
  for (const m of metrics) {
    const x = chartXMetric(mode, choice, m, declared);
    if (x) map[m] = x;
  }
  return map;
}

/** The points *metric*'s chart draws: the joined series once it has arrived
 *  (with its x metric), else the plain one on the step axis. */
export function chartPoints(
  series: Series, joined: Series | null, metric: string, xMap: XMap,
): { points: SeriesPoint[]; xMetric: string | null } {
  const xMetric = xMap[metric];
  const points = xMetric ? joined?.[metric] : undefined;
  if (points) return { points, xMetric };
  return { points: series[metric] ?? [], xMetric: null };
}

/** Training metrics with data, sorted: what the x-axis picker offers. */
export function xMetricOptions(series: Series): string[] {
  const names = Object.keys(series).filter((m) => series[m].length > 0);
  return splitSysMetrics(names).training.sort();
}

/** Tooltip label for an x-metric axis. */
export const xMetricLabel = (xMetric: string) => (x: number) => `${xMetric} ${x}`;
