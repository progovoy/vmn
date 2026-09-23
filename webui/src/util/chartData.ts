/** Pure builders for the training-curve charts (Run page and Overlay).
 *
 *  Each metric is built from its own points: a sparse `val_loss` logged every
 *  100 steps must survive next to a per-step `loss`, so nothing here ever
 *  downsamples one metric by another's x values. Rows are merged by x only
 *  for recharts' benefit, and every Line is drawn with `connectNulls`. */
import type { SeriesPoint } from "../types";
import { ema } from "../hooks/useSmoothing";
import { downsampleLTTB } from "./downsample";

export type XMode = "step" | "wall" | "relative";
export type ChartRow = Record<string, number>;
type Series = Record<string, SeriesPoint[]>;

/** Client-side safety cap per metric (the server already downsamples). */
export const MAX_POINTS_PER_METRIC = 2000;

const SYS_PREFIX = "sys_";

export function isSysMetric(name: string): boolean {
  return name.startsWith(SYS_PREFIX);
}

/** Training metrics and `sys_*` host metrics, each in their original order. */
export function splitSysMetrics(names: string[]): { training: string[]; system: string[] } {
  return {
    training: names.filter((n) => !isSysMetric(n)),
    system: names.filter(isSysMetric),
  };
}

const tsMs = (p: SeriesPoint) => (p.ts ? new Date(p.ts).getTime() : NaN);

/** Earliest timestamp across a run's series — its own start for "relative". */
export function runOrigin(series: Series, startedAt?: string | null): number {
  const started = startedAt ? new Date(startedAt).getTime() : NaN;
  if (Number.isFinite(started)) return started;
  let origin = Infinity;
  for (const pts of Object.values(series)) {
    for (const p of pts) {
      const t = tsMs(p);
      if (t < origin) origin = t;
    }
  }
  return origin;
}

/** x for one point. Step-less samples (system metrics) are placed by time,
 *  never by their array index, which would pile them onto steps 0..N. */
export function xOf(p: SeriesPoint, i: number, mode: XMode, origin: number): number | null {
  const t = tsMs(p);
  if (mode === "wall") return Number.isFinite(t) ? t : null;
  if (mode === "relative" || p.step == null) {
    if (Number.isFinite(t) && Number.isFinite(origin)) return (t - origin) / 1000;
    return p.step ?? i;
  }
  return p.step;
}

/** Downsample every metric on its own (LTTB keeps first and last points). */
export function capSeries(series: Series, maxPoints = MAX_POINTS_PER_METRIC): Series {
  const out: Series = {};
  for (const [name, pts] of Object.entries(series)) {
    if (pts.length <= maxPoints) {
      out[name] = pts;
      continue;
    }
    const keep = new Set(
      downsampleLTTB(pts.map((p, i) => ({ x: i, y: p.value ?? 0 })), maxPoints).map((d) => d.x),
    );
    out[name] = pts.filter((_, i) => keep.has(i));
  }
  return out;
}

function mergeInto(byX: Map<number, ChartRow>, x: number | null, key: string, value: unknown) {
  if (x === null || typeof value !== "number" || !Number.isFinite(value)) return;
  const row = byX.get(x) ?? { x };
  row[key] = value;
  byX.set(x, row);
}

const sortedRows = (byX: Map<number, ChartRow>) =>
  [...byX.values()].sort((a, b) => a.x - b.x);

/** Rows `{x, <metric>: value}` for one run's metrics. */
export function buildRows(
  series: Series, metrics: string[], mode: XMode, origin = runOrigin(series),
): ChartRow[] {
  const byX = new Map<number, ChartRow>();
  for (const m of metrics) {
    (series[m] ?? []).forEach((p, i) => mergeInto(byX, xOf(p, i, mode, origin), m, p.value));
  }
  return sortedRows(byX);
}

export interface OverlayRun {
  key: string;
  series: Series;
  origin: number;
}

/** Rows `{x, <run key>: value}` for one metric across runs; "relative" x is
 *  measured from each run's own origin so runs started days apart overlap. */
export function overlayRows(metric: string, runs: OverlayRun[], mode: XMode): ChartRow[] {
  const byX = new Map<number, ChartRow>();
  for (const run of runs) {
    (run.series[metric] ?? []).forEach((p, i) =>
      mergeInto(byX, xOf(p, i, mode, run.origin), run.key, p.value));
  }
  return sortedRows(byX);
}

/** Adds `<key>__smooth` next to each key, smoothing only that key's points. */
export function smoothRows(rows: ChartRow[], keys: string[], alpha: number): ChartRow[] {
  if (alpha === 0 || rows.length === 0) return rows;
  const out = rows.map((r) => ({ ...r }));
  for (const k of keys) {
    const sm = ema(rows.map((r) => r[k]), alpha);
    sm.forEach((v, i) => {
      if (v !== undefined) out[i][`${k}__smooth`] = v;
    });
  }
  return out;
}

/** Whether every point of every series carries a timestamp. */
export function allTimestamped(series: Series): boolean {
  return Object.values(series).every((pts) => pts.every((p) => p.ts != null));
}
