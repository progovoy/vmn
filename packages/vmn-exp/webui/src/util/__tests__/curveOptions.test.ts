import { describe, it, expect } from "vitest";
import { curveData, curveOptions, safeSplits, type CurveSeries } from "../curveOptions";

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

describe("curveOptions x range", () => {
  // uPlot's tick loop never ends on a zero-wide x range (all points at one
  // step, or one point): RangeError "Invalid array length" from its splits.
  type Range = (u: unknown, min: number, max: number) => [number, number];
  const range = () => curveOptions([s("a")], { xMode: "step", height: 100, theme, read }).scales!.x.range as Range;

  it("widens a zero-wide x range around its value", () => {
    const [lo, hi] = range()(null, 5, 5);
    expect(lo).toBeLessThan(5);
    expect(hi).toBeGreaterThan(5);
    expect(range()(null, 0, 0)).toEqual([-1, 1]);
  });

  it("keeps any other x range as it is", () => {
    expect(range()(null, 0, 60)).toEqual([0, 60]);
  });
});

describe("safeSplits", () => {
  // uPlot's own tick loop (val = roundDec(val + incr)) can stop advancing on
  // a near-flat axis (values ~1 varying by 1e-10): it never ends, RangeError.
  it("always ends, with at most 101 ticks", () => {
    const ticks = safeSplits(null, 0, 0.9999999999, 1.0000000001, 1e-11);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.length).toBeLessThanOrEqual(101);
    expect(safeSplits(null, 0, 0, 1, 1e-300).length).toBeLessThanOrEqual(101);
  });

  it("gives the usual ticks of an ordinary axis", () => {
    expect(safeSplits(null, 0, -0.05, 1.03, 0.2)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
  });

  it("is the linear axes' tick function, never a log axis's", () => {
    const lin = curveOptions([s("a")], { xMode: "step", height: 100, theme, read });
    const log = curveOptions([s("a")], { xMode: "step", height: 100, theme, read, logY: true });
    expect(lin.axes![0].splits).toBe(safeSplits);
    expect(lin.axes![1].splits).toBe(safeSplits);
    expect(log.axes![1].splits).toBeUndefined();
  });
});

describe("curveData of a near-flat chart", () => {
  // Values ~1 varying by 1e-10 leave uPlot no usable y scale (an empty
  // chart); a constant one it pads. The wobble is invisible at any size.
  it("plots a chart whose spread is below 1e-9 of its value as its mean", () => {
    const flat = s("a", { xs: Float64Array.from([0, 1, 2]), ys: Float64Array.from([1, 1.0000000001, 0.9999999999]) });
    const data = curveData([flat]) as unknown as [null, [Float64Array, Float64Array]];
    expect(new Set(data[1][1]).size).toBe(1);
    expect(data[1][1][0]).toBeCloseTo(1, 12);
    expect([...flat.ys]).toEqual([1, 1.0000000001, 0.9999999999]); // the series keeps its values
  });

  it("leaves a chart with a visible spread as it is", () => {
    const real = s("a", { xs: Float64Array.from([0, 1]), ys: Float64Array.from([0.7065, 0.7075]) });
    const data = curveData([real]) as unknown as [null, [Float64Array, Float64Array]];
    expect([...data[1][1]]).toEqual([0.7065, 0.7075]);
  });
});
