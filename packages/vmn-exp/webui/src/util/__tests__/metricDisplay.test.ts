import { describe, it, expect } from "vitest";
import { barStats, byValue, lastPerStep, splitCharts } from "../metricDisplay";
import type { SeriesPoint } from "../../types";

const p = (step: number | null, value: number): SeriesPoint => ({ step, value, ts: null });

describe("metricDisplay", () => {
  it("keeps the last value logged at each step, in step order", () => {
    expect(lastPerStep([p(2, 1), p(0, 5), p(2, 3), p(1, 4)])).toEqual([
      { step: 0, value: 5 }, { step: 1, value: 4 }, { step: 2, value: 3 },
    ]);
  });

  it("sorts bars by value, largest first, non-finite last", () => {
    const rows = [{ step: 0, value: 1 }, { step: 1, value: NaN }, { step: 2, value: 7 }];
    expect(byValue(rows).map((r) => r.step)).toEqual([2, 0, 1]);
  });

  it("gives the max and the share over a threshold", () => {
    const rows = [1, 2, 3, 4].map((value, step) => ({ step, value }));
    expect(barStats(rows, 2.5)).toEqual({ max: 4, over: 2, total: 4, share: 0.5 });
    expect(barStats([], 1)).toEqual({ max: null, over: 0, total: 0, share: null });
  });

  it("splits metrics into line metrics and those with another chart", () => {
    const charts = { a: "bars", c: "table" } as const;
    expect(splitCharts(["a", "b", "c"], charts)).toEqual([["b"], ["a", "c"]]);
    expect(splitCharts(["a"], undefined)).toEqual([["a"], []]);
  });
});
