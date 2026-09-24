import { describe, it, expect } from "vitest";
import { curveOptions } from "../curveOptions";
import { scatterOptions } from "../scatterOptions";

const theme = { axis: "#aaa", grid: "#222", text: "#bbb" };
type Values = (u: unknown, splits: number[], axisIdx: number, space: number, incr: number) => string[];

const distinct = (xs: string[]) => new Set(xs).size === xs.length;

describe("numeric axis ticks", () => {
  const y = () => curveOptions([], { xMode: "step", height: 100, theme }).axes?.[1].values as Values;

  it("chooses precision from the tick step so adjacent ticks differ", () => {
    const labels = y()(null, [0.00495, 0.004975, 0.005], 1, 30, 0.000025);
    expect(labels).toEqual(["0.004950", "0.004975", "0.005000"]);
  });

  it("keeps plain integers and simple decimals short", () => {
    expect(y()(null, [0, 50, 100], 1, 30, 50)).toEqual(["0", "50", "100"]);
    expect(y()(null, [0.1, 0.2, 0.3], 1, 30, 0.1)).toEqual(["0.1", "0.2", "0.3"]);
    expect(y()(null, [-0.25, 0, 0.25], 1, 30, 0.25)).toEqual(["-0.25", "0.00", "0.25"]);
  });

  it("uses exponent notation for very small or very large values, still distinct", () => {
    const small = y()(null, [1e-7, 2e-7, 3e-7], 1, 30, 1e-7);
    expect(distinct(small)).toBe(true);
    expect(small[0]).toMatch(/e-7$/);
    const big = y()(null, [1.0001e9, 1.0002e9], 1, 30, 1e5);
    expect(distinct(big)).toBe(true);
  });

  it("applies to both scatter axes", () => {
    const o = scatterOptions([], { height: 100, theme });
    for (const ax of o.axes ?? []) {
      const labels = (ax.values as Values)(null, [0.00495, 0.004975, 0.005], 0, 30, 0.000025);
      expect(distinct(labels)).toBe(true);
    }
  });
});
