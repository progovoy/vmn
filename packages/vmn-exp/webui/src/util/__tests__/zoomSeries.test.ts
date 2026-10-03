import { describe, it, expect } from "vitest";
import { isFullRange, spliceZoom } from "../zoomSeries";
import type { SeriesPoint } from "../../types";

const pts = (steps: number[], v = 0): SeriesPoint[] =>
  steps.map((step) => ({ step, value: v, ts: null }));

describe("spliceZoom", () => {
  it("replaces the coarse points inside the range with the zoomed ones", () => {
    const coarse = pts([0, 10, 20, 30, 40]);
    const zoomed = pts([10, 11, 12, 19, 20], 1);
    const out = spliceZoom(coarse, { range: [10, 20], points: zoomed });
    expect(out.map((p) => p.step)).toEqual([0, 10, 11, 12, 19, 20, 30, 40]);
    expect(out.filter((p) => p.value === 1)).toHaveLength(5);
  });

  it("is the coarse series without a zoom", () => {
    const coarse = pts([0, 1]);
    expect(spliceZoom(coarse, null)).toBe(coarse);
  });

  it("keeps step-less points out of the zoomed range", () => {
    const coarse = [...pts([0, 50]), { step: null, value: 3, ts: null }];
    const out = spliceZoom(coarse, { range: [40, 60], points: pts([45]) });
    expect(out.map((p) => p.step)).toEqual([0, 45, null]);
  });
});

describe("isFullRange", () => {
  it("tells a reset (the data's extent) from a zoom", () => {
    expect(isFullRange([0, 100], [0, 100])).toBe(true);
    expect(isFullRange([-1e-12, 100], [0, 100])).toBe(true);
    expect(isFullRange([5, 100], [0, 100])).toBe(false);
    expect(isFullRange([-10, 120], [0, 100])).toBe(true);
  });
});
