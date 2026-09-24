/** Pure geometry and data prep for the parallel-coordinates chart.
 *
 *  Every value is placed on its axis as t in [0, 1] (1 = top). Rows are
 *  precomputed once into a flat Float64Array (NaN = missing) so brushing and
 *  redraws never re-read row objects. */
import type { ExperimentRow } from "../types";
import { paramValue } from "../util";
import { isFiniteNumber } from "./stats";

export type Axis =
  | { kind: "num"; name: string; min: number; max: number }
  | { kind: "cat"; name: string; categories: string[] };

/** Brush ranges in t space, keyed by axis index. */
export type Brushes = Map<number, [number, number]>;

const isMissing = (v: unknown) => v === null || v === undefined;

export function rawValue(row: ExperimentRow, dim: string, metricCols: string[]): unknown {
  return metricCols.includes(dim) ? row.metrics[dim] : paramValue(row, dim);
}

/** A numeric axis when every present value is a finite number, else a
 *  categorical one over the values' string forms (sorted). */
function buildAxis(rows: ExperimentRow[], dim: string, metricCols: string[]): Axis {
  const values = rows.map((r) => rawValue(r, dim, metricCols)).filter((v) => !isMissing(v));
  const numeric = values.every((v) => typeof v === "number");
  if (!numeric) {
    return { kind: "cat", name: dim, categories: [...new Set(values.map(String))].sort() };
  }
  let min = Infinity, max = -Infinity;
  for (const v of values) {
    if (!isFiniteNumber(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === Infinity ? { kind: "num", name: dim, min: 0, max: 1 } : { kind: "num", name: dim, min, max };
}

export function buildAxes(rows: ExperimentRow[], dims: string[], metricCols: string[]): Axis[] {
  return dims.map((d) => buildAxis(rows, d, metricCols));
}

export function axisT(axis: Axis, v: unknown): number | null {
  if (axis.kind === "num") {
    if (!isFiniteNumber(v)) return null;
    return axis.max === axis.min ? 0.5 : (v - axis.min) / (axis.max - axis.min);
  }
  if (isMissing(v)) return null;
  const i = axis.categories.indexOf(String(v));
  if (i < 0) return null;
  return axis.categories.length === 1 ? 0.5 : i / (axis.categories.length - 1);
}

/** Row-major t matrix: `m[row * dims + axis]`, NaN for a missing value. */
export function buildMatrix(
  rows: ExperimentRow[], dims: string[], metricCols: string[], axes: Axis[],
): Float64Array {
  const m = new Float64Array(rows.length * dims.length);
  rows.forEach((r, ri) => dims.forEach((d, di) => {
    m[ri * dims.length + di] = axisT(axes[di], rawValue(r, d, metricCols)) ?? NaN;
  }));
  return m;
}

/** Brush comparisons tolerate float noise at the brush edges. */
const EPS = 1e-9;

/** Indices of rows inside every brush, or null when nothing is brushed. */
export function selectRows(m: Float64Array, nDims: number, brushes: Brushes): number[] | null {
  if (brushes.size === 0 || nDims === 0) return null;
  const out: number[] = [];
  const nRows = m.length / nDims;
  for (let r = 0; r < nRows; r++) {
    let inside = true;
    for (const [d, [a, b]] of brushes) {
      const t = m[r * nDims + d];
      if (!(t >= Math.min(a, b) - EPS && t <= Math.max(a, b) + EPS)) { inside = false; break; }
    }
    if (inside) out.push(r);
  }
  return out;
}

export const yFromT = (t: number, top: number, plotH: number) => top + plotH - t * plotH;
export const tFromY = (y: number, top: number, plotH: number) => (top + plotH - y) / plotH;

/** Sequential ramp, dark-background friendly: muted indigo -> bright yellow. */
const STOPS: [number, number, number][] = [
  [74, 61, 143], [58, 111, 176], [42, 161, 152], [124, 197, 97], [242, 214, 75],
];

export function colorScale(t: number): string {
  const c = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(c));
  const f = c - i;
  const [r, g, b] = STOPS[i].map((v, k) => Math.round(v + (STOPS[i + 1][k] - v) * f));
  return `rgb(${r}, ${g}, ${b})`;
}

/** Each row's target value as t, with the best value at 1 for either goal. */
export function targetTs(rows: ExperimentRow[], metric: string, goal: "min" | "max"): (number | null)[] {
  const axis = buildAxis(rows, metric, [metric]);
  return rows.map((r) => {
    const t = axis.kind === "num" ? axisT(axis, r.metrics[metric]) : null;
    return t === null ? null : goal === "min" ? 1 - t : t;
  });
}
