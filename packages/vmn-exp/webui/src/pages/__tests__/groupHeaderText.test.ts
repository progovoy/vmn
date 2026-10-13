import { describe, it, expect } from "vitest";
import { aggregateCell, countParts, countsText, spokenCounts } from "../groupHeaderText";

const counts = (extra = {}) => ({ total: 16, running: 2, waiting: 0, done: 13, failed: 1, stuck: 0, ...extra });
const agg = (extra = {}) => ({ mean: 0.5, best: 0.2, median: 0.4, min: 0.2, max: 0.9, n: 16, ...extra });

describe("a group header's status count (plan 22 G4)", () => {
  it("reads the total, then every state that is not done, in words", () => {
    expect(countsText(counts())).toBe("16 · 2 running · 1 failed");
    expect(countsText(counts({ running: 0, failed: 0, waiting: 3, stuck: 1 }))).toBe("16 · 3 waiting · 1 stuck");
    expect(countsText(counts({ total: 4, running: 0, failed: 0 }))).toBe("4");
  });

  it("tags each part with its state, so it can be coloured", () => {
    expect(countParts(counts()).map((p) => p.tone)).toEqual(["total", "running", "failed"]);
  });

  it("says the counts in words for a screen reader", () => {
    expect(spokenCounts(counts())).toBe("16 runs, 2 running, 1 failed");
    expect(spokenCounts(counts({ total: 1, running: 0, failed: 0 }))).toBe("1 run");
  });
});

describe("a group header's aggregate cell (plan 22 G10)", () => {
  it("shows the chosen aggregate and names it with its count", () => {
    expect(aggregateCell(agg(), "mean")).toEqual({ value: 0.5, title: "mean of 16" });
    expect(aggregateCell(agg(), "median")).toEqual({ value: 0.4, title: "median of 16" });
    expect(aggregateCell(agg(), "best")).toEqual({ value: 0.2, title: "best of 16" });
  });

  it("falls back to the mean for a metric without a goal, and says so", () => {
    expect(aggregateCell(agg({ best: null }), "best")).toEqual({ value: 0.5, title: "mean of 16 (no goal)" });
  });

  it("is empty when the group has no value of the metric", () => {
    expect(aggregateCell(undefined, "mean")).toEqual({ value: null, title: undefined });
    expect(aggregateCell(agg({ mean: null, n: 0 }), "mean")).toEqual({ value: null, title: undefined });
  });
});
