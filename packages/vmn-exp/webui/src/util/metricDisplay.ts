/** Plan 28 N8: metrics a `chart` hint draws other than as a curve. `bars`
 *  shows the last value per step sorted by value (the step is a label, not
 *  an axis: per-member metrics log members in no stable order), `table`
 *  lists step -> value. */
import type { MetricChart, MetricSteps, SeriesPoint } from "../types";

export interface StepValue {
  step: number | null;
  value: number;
}

/** The last value logged at each step, steps ascending (step-less last). */
export function lastPerStep(points: SeriesPoint[]): StepValue[] {
  const last = new Map<number | null, number>();
  for (const p of points) last.set(p.step, p.value);
  return [...last].map(([step, value]) => ({ step, value }))
    .sort((a, b) => (a.step ?? Infinity) - (b.step ?? Infinity));
}

/** The server's unthinned *steps* of a metric when it sent them, else the
 *  last value per step of its (possibly thinned) *points*. */
export function stepRows(steps: MetricSteps | undefined, points: SeriesPoint[]): StepValue[] {
  if (!steps) return lastPerStep(points);
  return steps.rows.map((r) => ({ step: r.step, value: r.value ?? NaN }));
}

/** *rows* largest value first, non-finite values last. */
export function byValue(rows: StepValue[]): StepValue[] {
  const key = (v: number) => (Number.isFinite(v) ? v : -Infinity);
  return [...rows].sort((a, b) => key(b.value) - key(a.value));
}

export interface BarStats {
  max: number | null;
  over: number;
  total: number;
  share: number | null;
}

/** The largest finite value of *rows*, and how many are over *threshold*. */
export function barStats(rows: StepValue[], threshold: number): BarStats {
  const finite = rows.map((r) => r.value).filter(Number.isFinite);
  const over = finite.filter((v) => v > threshold).length;
  return {
    max: finite.length ? Math.max(...finite) : null,
    over,
    total: rows.length,
    share: rows.length ? over / rows.length : null,
  };
}

/** *metrics* split into `[drawn as lines, with another chart]`. */
export function splitCharts(
  metrics: string[], charts: Record<string, MetricChart> | undefined,
): [string[], string[]] {
  if (!charts) return [metrics, []];
  return [metrics.filter((m) => !charts[m]), metrics.filter((m) => charts[m])];
}
