/** Pure builders for the training-curve charts (Run page and Overlay).
 *
 *  Each metric is built from its own points: a sparse `val_loss` logged every
 *  100 steps must survive next to a per-step `loss`, so nothing here ever
 *  downsamples one metric by another's x values. The canvas charts build their
 *  typed per-curve arrays from these in seriesArrays.ts. */
import type { SeriesPoint } from "../types";

export type XMode = "step" | "wall" | "relative";
type Series = Record<string, SeriesPoint[]>;

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

/** Whether every point of every series carries a timestamp. */
export function allTimestamped(series: Series): boolean {
  return Object.values(series).every((pts) => pts.every((p) => p.ts != null));
}
