/** Pure data prep for the metric scatter: typed point arrays split into the
 *  "rest" and "best" groups (or one per group colour on a grouped board), and
 *  a nearest-point lookup for hover/click. */
import type { ExperimentRow } from "../types";
import { paramValue } from "../util";
import { finiteOrNull } from "./stats";

export interface PointGroup {
  xs: Float64Array;
  ys: Float64Array;
  verstrs: string[];
  idxs: number[];
}

export interface ScatterPoint {
  x: number;
  y: number;
  verstr: string;
  idx: number;
}

function numericValue(row: ExperimentRow, col: string, paramCols: string[]): number | null {
  return finiteOrNull(paramCols.includes(col) ? paramValue(row, col) : row.metrics[col]);
}

function toGroup(points: ScatterPoint[]): PointGroup {
  return {
    xs: Float64Array.from(points, (p) => p.x),
    ys: Float64Array.from(points, (p) => p.y),
    verstrs: points.map((p) => p.verstr),
    idxs: points.map((p) => p.idx),
  };
}

/** Rows with finite x and y, split by whether y is the best value (per goal).
 *  When goal is null no point is marked as best. */
export function scatterGroups(
  rows: ExperimentRow[], xCol: string, yCol: string, paramCols: string[], goal: "min" | "max" | null,
  yParamCols: string[] = paramCols,
): { rest: PointGroup; best: PointGroup } {
  const points: ScatterPoint[] = [];
  let bestY = goal === "min" ? Infinity : goal === "max" ? -Infinity : null;
  for (const r of rows) {
    const x = numericValue(r, xCol, paramCols);
    const y = numericValue(r, yCol, yParamCols);
    if (x === null || y === null) continue;
    points.push({ x, y, verstr: r.verstr, idx: r.idx });
    if (bestY !== null && (goal === "min" ? y < bestY : y > bestY)) bestY = y;
  }
  return {
    rest: toGroup(points.filter((p) => bestY === null || p.y !== bestY)),
    best: toGroup(points.filter((p) => bestY !== null && p.y === bestY)),
  };
}

/** Rows with finite x and y, one group per colour: *colorOf*'s colours in
 *  first-seen order of *colors*, and *fallback* for a run without one. */
export function colorGroups(
  rows: ExperimentRow[], xCol: string, yCol: string, paramCols: string[],
  colorOf: ReadonlyMap<string, string>, fallback: string, yParamCols: string[] = paramCols,
): { colors: string[]; groups: PointGroup[] } {
  const byColor = new Map<string, ScatterPoint[]>();
  for (const r of rows) {
    const x = numericValue(r, xCol, paramCols);
    const y = numericValue(r, yCol, yParamCols);
    if (x === null || y === null) continue;
    const color = colorOf.get(r.verstr) ?? fallback;
    const points = byColor.get(color);
    const p = { x, y, verstr: r.verstr, idx: r.idx };
    if (points) points.push(p); else byColor.set(color, [p]);
  }
  return { colors: [...byColor.keys()], groups: [...byColor.values()].map(toGroup) };
}

function span(groups: PointGroup[], key: "xs" | "ys"): number {
  let lo = Infinity, hi = -Infinity;
  for (const g of groups) {
    for (const v of g[key]) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  return hi > lo ? hi - lo : 1;
}

/** The point closest to (x, y), distances measured as fractions of each
 *  axis' data span; null when none lies within *radius* of it. The linear
 *  reference scan: the chart hovers through `pointGrid`, checked against this. */
export function nearestPoint(
  groups: PointGroup[], x: number, y: number, radius: number,
): ScatterPoint | null {
  const sx = span(groups, "xs"), sy = span(groups, "ys");
  let best: ScatterPoint | null = null;
  let bestD = radius * radius;
  for (const g of groups) {
    for (let i = 0; i < g.xs.length; i++) {
      const dx = (g.xs[i] - x) / sx, dy = (g.ys[i] - y) / sy;
      const d = dx * dx + dy * dy;
      if (d <= bestD) {
        bestD = d;
        best = { x: g.xs[i], y: g.ys[i], verstr: g.verstrs[i], idx: g.idxs[i] };
      }
    }
  }
  return best;
}
