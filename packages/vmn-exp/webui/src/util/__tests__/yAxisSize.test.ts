/** Plan 20 E5: the y axis is as wide as its widest tick label, so labels
 *  like 1.792e+9 are never clipped (the axis was a fixed 56px). */
import { describe, it, expect } from "vitest";
import { curveOptions, yAxisSize, Y_AXIS_SIZE } from "../curveOptions";
import { scatterOptions } from "../scatterOptions";

type SizeFn = (u: unknown, values: string[] | null, axisIdx: number, cycle: number) => number;
const theme = { axis: "#aaa", grid: "#222", text: "#bbb" };

describe("yAxisSize", () => {
  it("keeps the old width as the floor for short labels", () => {
    expect(yAxisSize(null, ["0.1", "0.25"])).toBe(Y_AXIS_SIZE);
    expect(yAxisSize(null, null)).toBe(Y_AXIS_SIZE);
  });

  it("grows for a wide label", () => {
    const wide = yAxisSize(null, ["1.000e+9", "1.792e+9"]);
    expect(wide).toBeGreaterThan(Y_AXIS_SIZE);
    expect(yAxisSize(null, ["-1.792e+12"])).toBeGreaterThan(wide);
  });

  it("sizes the line and scatter charts' y axes", () => {
    const line = curveOptions([], { xMode: "step", height: 100, theme }).axes?.[1].size as SizeFn;
    expect(line(null, ["1.792e+9"], 1, 0)).toBeGreaterThan(Y_AXIS_SIZE);
    const scatter = scatterOptions([], { height: 100, theme }).axes?.[1].size as SizeFn;
    expect(scatter(null, ["1.792e+9"], 1, 0)).toBeGreaterThan(Y_AXIS_SIZE);
  });
});
