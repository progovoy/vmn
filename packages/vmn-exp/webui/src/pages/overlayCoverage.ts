/** Which overlay runs each chart draws when runs log different metrics: a
 *  metric gets a chart when any selected run has a curve for it, and each
 *  chart draws just the runs that have one. */
import type { SeriesPoint } from "../types";
import type { OverlayRunData } from "./overlaySeries";

type Joined = Record<string, Record<string, SeriesPoint[]>>;

export interface MetricCurve {
  key: string;
  points: SeriesPoint[];
  origin: number;
}

/** A single point draws no line, so a curve needs two. */
const isCurve = (points: SeriesPoint[] | undefined) => (points?.length ?? 0) > 1;

const curveMetrics = (run: OverlayRunData) =>
  Object.keys(run.series).filter((m) => isCurve(run.series[m]));

/** Metrics with a curve in at least one run, sorted. */
export function unionMetrics(runs: OverlayRunData[]): string[] {
  return [...new Set(runs.flatMap(curveMetrics))].sort();
}

/** Runs without a single curve. */
export function curvelessRuns(runs: OverlayRunData[]): OverlayRunData[] {
  return runs.filter((r) => curveMetrics(r).length === 0);
}

/** `@N name`, `@N`, else the verstr. */
export function runLabel(run: OverlayRunData): string {
  if (run.idx == null) return run.key;
  return run.name ? `@${run.idx} ${run.name}` : `@${run.idx}`;
}

/** One line naming the curveless runs, or null when every run has a curve. */
export function noCurvesNote(runs: OverlayRunData[]): string | null {
  const none = curvelessRuns(runs);
  if (none.length === 0) return null;
  const labels = none.map((r) =>
    r.kind === "outer" ? `${runLabel(r)} (sweep run; its trials log the curves)` : runLabel(r));
  return `No curves: ${labels.join(", ")}`;
}

/** *metric*'s curves among the runs with a curve for it: on *xMetric* for
 *  those whose join has points, else (no join yet, or none has the x metric)
 *  their plain series. */
export function metricCurves(
  metric: string, runs: OverlayRunData[], xMetric: string | null, joined: Joined | null,
): { xMetric: string | null; curves: MetricCurve[] } {
  const drawn = runs.filter((r) => isCurve(r.series[metric]));
  const pick = (series: (r: OverlayRunData) => SeriesPoint[] | undefined) => drawn
    .filter((r) => (series(r)?.length ?? 0) > 0)
    .map((r) => ({ key: r.key, points: series(r)!, origin: r.origin }));
  if (xMetric && joined) {
    const curves = pick((r) => joined[r.key]?.[metric]);
    if (curves.length > 0) return { xMetric, curves };
  }
  return { xMetric: null, curves: pick((r) => r.series[metric]) };
}
