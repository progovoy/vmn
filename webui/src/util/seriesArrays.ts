/** Typed-array series for the canvas charts: one `{xs, ys}` pair per curve,
 *  never merged onto a shared x axis, so 100 runs x 10k points stay 100
 *  compact arrays instead of a million-cell table of mostly-empty rows. */
import type { SeriesPoint } from "../types";
import { xOf, type XMode } from "./chartData";
import { isFiniteNumber } from "./stats";

export interface XYSeries {
  xs: Float64Array;
  ys: Float64Array;
}

/** Finite points of one series, sorted by x. `positiveOnly` is for a log
 *  axis, which cannot place zero or a negative value. */
export function toXY(
  points: SeriesPoint[], mode: XMode, origin: number, opts: { positiveOnly?: boolean } = {},
): XYSeries {
  const xs: number[] = [];
  const ys: number[] = [];
  let sorted = true;
  points.forEach((p, i) => {
    const x = xOf(p, i, mode, origin);
    if (x === null || !isFiniteNumber(p.value)) return;
    if (opts.positiveOnly && p.value <= 0) return;
    if (xs.length && x < xs[xs.length - 1]) sorted = false;
    xs.push(x);
    ys.push(p.value);
  });
  if (sorted) return { xs: Float64Array.from(xs), ys: Float64Array.from(ys) };
  const order = xs.map((_, i) => i).sort((a, b) => xs[a] - xs[b]);
  return {
    xs: Float64Array.from(order, (i) => xs[i]),
    ys: Float64Array.from(order, (i) => ys[i]),
  };
}

/** Exponential moving average over gap-free values (see `ema`). */
export function emaXY(ys: Float64Array, alpha: number): Float64Array {
  if (alpha === 0) return ys;
  const out = new Float64Array(ys.length);
  let prev = ys[0];
  for (let i = 0; i < ys.length; i++) {
    prev = i === 0 ? ys[0] : alpha * prev + (1 - alpha) * ys[i];
    out[i] = prev;
  }
  return out;
}

/** Index of the x closest to *x* in sorted *xs*, or -1 when empty. */
export function nearestIndex(xs: Float64Array, x: number): number {
  if (xs.length === 0) return -1;
  let lo = 0;
  let hi = xs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && x - xs[lo - 1] <= xs[lo] - x ? lo - 1 : lo;
}

export interface TooltipRow {
  key: string;
  x: number;
  value: number;
}

/** Each series' point nearest *x*. Past *limit* rows only those whose value
 *  is closest to the cursor's *y* are kept; rows are sorted largest first. */
export function tooltipRows(
  series: ({ key: string } & XYSeries)[], x: number, y: number | null, limit: number,
): TooltipRow[] {
  const rows: TooltipRow[] = [];
  for (const s of series) {
    const i = nearestIndex(s.xs, x);
    if (i >= 0) rows.push({ key: s.key, x: s.xs[i], value: s.ys[i] });
  }
  const near = y === null || rows.length <= limit
    ? rows
    : [...rows].sort((a, b) => Math.abs(a.value - y) - Math.abs(b.value - y));
  return near.slice(0, limit).sort((a, b) => b.value - a.value);
}

/** Metric names containing *query*, case-insensitively. */
export function filterMetrics(names: string[], query: string): string[] {
  const q = query.trim().toLowerCase();
  return q ? names.filter((n) => n.toLowerCase().includes(q)) : names;
}
