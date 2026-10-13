/** The scatter's hover lookup (plan 23 W4): grid buckets answer what the
 *  linear nearestPoint scan does, without visiting every point. */
import { describe, it, expect } from "vitest";
import { nearestPoint, type PointGroup } from "../scatterData";
import { pointGrid } from "../pointGrid";

function group(points: [number, number][], tag: string): PointGroup {
  return {
    xs: Float64Array.from(points, (p) => p[0]),
    ys: Float64Array.from(points, (p) => p[1]),
    verstrs: points.map((_, i) => `${tag}${i}`),
    idxs: points.map((_, i) => i),
  };
}

/** A deterministic pseudo-random cloud. */
function cloud(n: number, seed: number): [number, number][] {
  let s = seed;
  const next = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
  return Array.from({ length: n }, () => [next() * 100, next() * 3 - 1] as [number, number]);
}

describe("pointGrid", () => {
  it("finds the same nearest point as the linear scan", () => {
    const groups = [group(cloud(800, 1), "a"), group(cloud(700, 2), "b")];
    const grid = pointGrid(groups, 0.03);
    for (const [x, y] of cloud(300, 3)) {
      const want = nearestPoint(groups, x, y, 0.03);
      const got = grid.nearest(x, y);
      expect(got?.verstr ?? null).toBe(want?.verstr ?? null);
    }
  });

  it("answers null far from every point and for no points", () => {
    expect(pointGrid([group([[0, 0], [1, 1]], "a")], 0.03).nearest(0.5, 0.5)).toBeNull();
    expect(pointGrid([], 0.03).nearest(0, 0)).toBeNull();
  });

  it("finds a point outside the data's span (a zoomed-out cursor)", () => {
    const grid = pointGrid([group([[0, 0], [10, 10]], "a")], 0.03);
    expect(grid.nearest(10.1, 10.1)?.verstr).toBe("a1");
    expect(grid.nearest(-0.1, 0)?.verstr).toBe("a0");
  });
});
