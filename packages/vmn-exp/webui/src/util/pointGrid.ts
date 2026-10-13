/** A grid-bucket lookup of the scatter's points (plan 23 W4): hover over a
 *  50k-point cloud visits the 3x3 cells around the cursor, not every point.
 *  Distances are fractions of each axis' data span, as in `nearestPoint`. */
import type { PointGroup, ScatterPoint } from "./scatterData";

export interface PointGrid {
  /** The point closest to (x, y) within the grid's radius, else null. */
  nearest: (x: number, y: number) => ScatterPoint | null;
}

interface Flat { xs: number[]; ys: number[]; verstrs: string[]; idxs: number[] }

function flatten(groups: PointGroup[]): Flat {
  const flat: Flat = { xs: [], ys: [], verstrs: [], idxs: [] };
  for (const g of groups) {
    for (let i = 0; i < g.xs.length; i++) {
      flat.xs.push(g.xs[i]); flat.ys.push(g.ys[i]);
      flat.verstrs.push(g.verstrs[i]); flat.idxs.push(g.idxs[i]);
    }
  }
  return flat;
}

/** The values' low end and span (1 for a single value). */
function extent(values: number[]): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
  return [lo, hi > lo ? hi - lo : 1];
}

const cellKey = (cx: number, cy: number) => `${cx},${cy}`;

/** Buckets of side *radius* (in span fractions), so a hit lies in the
 *  cursor's cell or a neighbour. Ties go to the later point, as in the scan. */
export function pointGrid(groups: PointGroup[], radius: number): PointGrid {
  const f = flatten(groups);
  const [x0, sx] = extent(f.xs), [y0, sy] = extent(f.ys);
  const cell = (v: number, lo: number, span: number) => Math.floor((v - lo) / span / radius);
  const cells = new Map<string, number[]>();
  for (let i = 0; i < f.xs.length; i++) {
    const key = cellKey(cell(f.xs[i], x0, sx), cell(f.ys[i], y0, sy));
    const bucket = cells.get(key);
    if (bucket) bucket.push(i); else cells.set(key, [i]);
  }
  const nearest = (x: number, y: number): ScatterPoint | null => {
    const cx = cell(x, x0, sx), cy = cell(y, y0, sy);
    let best = -1, bestD = radius * radius;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const i of cells.get(cellKey(cx + dx, cy + dy)) ?? []) {
          const ex = (f.xs[i] - x) / sx, ey = (f.ys[i] - y) / sy;
          const d = ex * ex + ey * ey;
          if (d < bestD || (d === bestD && i > best)) { bestD = d; best = i; }
        }
      }
    }
    return best < 0 ? null : { x: f.xs[best], y: f.ys[best], verstr: f.verstrs[best], idx: f.idxs[best] };
  };
  return { nearest };
}
