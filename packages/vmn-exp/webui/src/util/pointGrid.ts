/** A grid-bucket lookup of the scatter's points (plan 23 W4): hover over a
 *  50k-point cloud visits the 3x3 cells around the cursor, not every point.
 *  Distances are fractions of each axis' data span, as in `nearestPoint`
 *  (kept as the reference scan the tests check this against). */
import type { PointGroup, ScatterPoint } from "./scatterData";

export interface PointGrid {
  /** The point closest to (x, y) within the grid's radius, else null. */
  nearest: (x: number, y: number) => ScatterPoint | null;
}

/** Every group's coordinates in one pair of typed arrays, plus where each group starts. */
function flatten(groups: PointGroup[]) {
  const n = groups.reduce((s, g) => s + g.xs.length, 0);
  const xs = new Float64Array(n), ys = new Float64Array(n);
  const starts: number[] = [];
  let at = 0;
  for (const g of groups) {
    starts.push(at);
    xs.set(g.xs, at); ys.set(g.ys, at);
    at += g.xs.length;
  }
  return { xs, ys, starts };
}

/** The values' low end and span (1 for a single value). */
function extent(values: Float64Array): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
  return [lo, hi > lo ? hi - lo : 1];
}

/** A cell's numeric key; cells off the data (a zoomed-out cursor) stay distinct. */
const cellKey = (cx: number, cy: number) => cx * 1_000_003 + cy;

/** Buckets of side *radius* (in span fractions), so a hit lies in the
 *  cursor's cell or a neighbour. Ties go to the later point, as in the scan. */
export function pointGrid(groups: PointGroup[], radius: number): PointGrid {
  const { xs, ys, starts } = flatten(groups);
  const [x0, sx] = extent(xs), [y0, sy] = extent(ys);
  const cell = (v: number, lo: number, span: number) => Math.floor((v - lo) / span / radius);
  const cells = new Map<number, number[]>();
  for (let i = 0; i < xs.length; i++) {
    const key = cellKey(cell(xs[i], x0, sx), cell(ys[i], y0, sy));
    const bucket = cells.get(key);
    if (bucket) bucket.push(i); else cells.set(key, [i]);
  }
  const pointAt = (i: number): ScatterPoint => {
    let g = starts.length - 1;
    while (starts[g] > i) g--;
    const j = i - starts[g];
    return { x: xs[i], y: ys[i], verstr: groups[g].verstrs[j], idx: groups[g].idxs[j] };
  };
  const nearest = (x: number, y: number): ScatterPoint | null => {
    const cx = cell(x, x0, sx), cy = cell(y, y0, sy);
    let best = -1, bestD = radius * radius;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const i of cells.get(cellKey(cx + dx, cy + dy)) ?? []) {
          const ex = (xs[i] - x) / sx, ey = (ys[i] - y) / sy;
          const d = ex * ex + ey * ey;
          if (d < bestD || (d === bestD && i > best)) { bestD = d; best = i; }
        }
      }
    }
    return best < 0 ? null : pointAt(best);
  };
  return { nearest };
}
