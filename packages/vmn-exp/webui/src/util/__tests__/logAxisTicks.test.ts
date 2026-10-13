import { describe, it, expect } from "vitest";
import { curveOptions, fmtLogTicks, themedAxis } from "../curveOptions";

const theme = { axis: "#aaa", grid: "#222", text: "#bbb" };
type Values = (u: unknown, splits: (number | null)[], axisIdx: number, space: number, incr: number) => string[];

describe("log y axis ticks", () => {
  const logY = () => curveOptions([], { xMode: "step", height: 100, theme, logY: true }).axes?.[1].values as Values;

  it("labels every tick with its own value, never a run of zeros", () => {
    // uPlot hands a log axis the linear increment of the whole range (0.1
    // here) and null for the splits it filters out.
    const splits = [0.0001, 0.0002, null, 0.001, 0.01, 0.1, 1, 10];
    expect(logY()(null, splits, 1, 30, 0.1)).toEqual(["1e-4", "2e-4", "", "0.001", "0.01", "0.1", "1", "10"]);
  });

  it("writes big and tiny magnitudes compactly, without float noise", () => {
    expect(fmtLogTicks([1e-7, 3.0000000000000004e-5, 1e6, 2e9, 100, 0.005])).toEqual(
      ["1e-7", "3e-5", "1e6", "2e9", "100", "0.005"],
    );
  });

  it("keeps the linear formatter on a linear axis", () => {
    const y = curveOptions([], { xMode: "step", height: 100, theme }).axes?.[1].values as Values;
    expect(y(null, [0, 0.5, 1], 1, 30, 0.5)).toEqual(["0.0", "0.5", "1.0"]);
  });
});

describe("axis font", () => {
  it("has a whole-pixel size uPlot can scale for a hi-dpi canvas", () => {
    // uPlot multiplies the first /(\d+)px/ by devicePixelRatio: "10.5px"
    // became "10.10px", a 5px label on a 2x screen.
    const font = String(themedAxis(theme).font);
    const scaled = font.replace(/(\d+)px/, (_m, p: string) => `${Number(p) * 2}px`);
    expect(Number(/^([\d.]+)px/.exec(scaled)?.[1])).toBeGreaterThanOrEqual(22);
  });
});
