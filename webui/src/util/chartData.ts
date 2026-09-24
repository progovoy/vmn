/** Pure builders for the training-curve charts (Run page and Overlay).
 *
 *  Each metric is built from its own points: a sparse `val_loss` logged every
 *  100 steps must survive next to a per-step `loss`, so nothing here ever
 *  downsamples one metric by another's x values. The canvas charts build their
 *  typed per-curve arrays from these in seriesArrays.ts. */
import type { SeriesPoint } from "../types";
import { downsampleLTTB } from "./downsample";

export type XMode = "step" | "wall" | "relative";
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

/** Whether every point of every series carries a timestamp. */
export function allTimestamped(series: Series): boolean {
  return Object.values(series).every((pts) => pts.every((p) => p.ts != null));
}
