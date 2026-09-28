import { describe, it, expect, vi } from "vitest";
import { dotCenters, scatterOptions } from "../scatterOptions";

const theme = { axis: "#aaa", grid: "#222", text: "#bbb" };

describe("dotCenters", () => {
  it("maps in-view points to canvas pixels and skips the rest", () => {
    const xs = Float64Array.from([0, 5, 20]);
    const ys = Float64Array.from([1, 2, 3]);
    const out = dotCenters(xs, ys, (x) => x * 10, (y) => 100 - y, { xMin: 0, xMax: 10, yMin: 0, yMax: 10 });
    expect([...out]).toEqual([0, 99, 50, 98]);
  });
});

describe("scatterOptions", () => {
  it("fills each group in its colour with a custom dots path (faceted mode draws no built-in points)", () => {
    const o = scatterOptions(["#0000ff", "#00ff00"], { height: 300, theme });
    expect(o.mode).toBe(2);
    expect(o.series.slice(1).map((s) => s.fill)).toEqual(["#0000ff", "#00ff00"]);
    for (const s of o.series.slice(1)) expect(typeof s.paths).toBe("function");
  });

  it("draws a circle per visible point", () => {
    const arcs = vi.fn();
    class FakePath { moveTo() {} arc(...a: unknown[]) { arcs(...a); } }
    vi.stubGlobal("Path2D", FakePath);
    try {
      const o = scatterOptions(["#00f"], { height: 300, theme });
      const u = {
        data: [null, [Float64Array.from([1, 2]), Float64Array.from([3, 4])]],
        scales: { x: { min: 0, max: 10 }, y: { min: 0, max: 10 } },
        valToPos: (v: number) => v,
      };
      const paths = (o.series[1].paths as unknown as (u: unknown, i: number) => { fill: unknown })(u, 1);
      expect(paths.fill).toBeInstanceOf(FakePath);
      expect(arcs).toHaveBeenCalledTimes(2);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
