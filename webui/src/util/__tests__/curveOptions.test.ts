import { describe, it, expect } from "vitest";
import { curveData, curveOptions, type CurveSeries } from "../curveOptions";

const theme = { axis: "#aaa", grid: "#222", text: "#bbb" };
const read = (name: string) => (name === "--minor" ? "#4d8df6" : "");
const s = (key: string, extra: Partial<CurveSeries> = {}): CurveSeries => ({
  key, label: key, color: "var(--minor)",
  xs: Float64Array.from([0, 1]), ys: Float64Array.from([1, 2]), ...extra,
});

describe("curveData", () => {
  it("gives every series its own x/y arrays (uPlot mode 2), no shared x", () => {
    const a = s("a"), b = s("b", { xs: Float64Array.from([5]), ys: Float64Array.from([9]) });
    const data = curveData([a, b]);
    expect(data[0]).toBeNull();
    expect(data[1]).toEqual([a.xs, a.ys]);
    expect(data[2]).toEqual([b.xs, b.ys]);
  });
});

describe("curveOptions", () => {
  const base = { xMode: "step" as const, height: 200, theme, read };

  it("uses faceted mode with the built-in legend off", () => {
    const o = curveOptions([s("a"), s("b")], base);
    expect(o.mode).toBe(2);
    expect(o.legend?.show).toBe(false);
    expect(o.series).toHaveLength(3);
    expect(o.height).toBe(200);
  });

  it("resolves CSS variable colours for the canvas", () => {
    const o = curveOptions([s("a")], base);
    expect(o.series[1].stroke).toBe("#4d8df6");
  });

  it("styles axes and grid from the theme", () => {
    const o = curveOptions([s("a")], base);
    for (const ax of o.axes ?? []) {
      expect(ax.stroke).toBe("#aaa");
      expect(ax.grid?.stroke).toBe("#222");
    }
  });

  it("draws raw (faded) series thin and translucent", () => {
    const o = curveOptions([s("a", { faded: true }), s("b")], base);
    expect(o.series[1].alpha).toBeLessThan(1);
    expect(o.series[2].alpha ?? 1).toBe(1);
    expect(o.series[1].width).toBeLessThan(o.series[2].width as number);
  });

  it("switches the y scale to log", () => {
    expect(curveOptions([s("a")], { ...base, logY: true }).scales?.y?.distr).toBe(3);
    expect(curveOptions([s("a")], base).scales?.y?.distr).toBe(1);
  });

  it("formats wall-clock x ticks as times", () => {
    const o = curveOptions([s("a")], { ...base, xMode: "wall" });
    const values = o.axes?.[0].values as (u: unknown, splits: number[]) => string[];
    const ms = new Date(2026, 0, 1, 9, 5, 7).getTime();
    expect(values(null, [ms])).toEqual(["09:05:07"]);
  });

  it("formats relative x ticks as durations", () => {
    const o = curveOptions([s("a")], { ...base, xMode: "relative" });
    const values = o.axes?.[0].values as (u: unknown, splits: number[]) => string[];
    expect(values(null, [30, 120])).toEqual(["30s", "2m"]);
  });
});
