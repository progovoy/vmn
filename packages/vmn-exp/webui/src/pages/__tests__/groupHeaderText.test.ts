import { describe, it, expect } from "vitest";
import { aggregateCell, countParts, countsText, spokenCounts } from "../groupHeaderText";

const counts = (extra = {}) => ({ total: 16, running: 2, waiting: 0, done: 13, failed: 1, stuck: 0, ...extra });
const agg = (extra = {}) => ({ mean: 0.5, best: 0.2, median: 0.4, min: 0.2, max: 0.9, n: 16, ...extra });

describe("a group header's status count (plan 22 G4)", () => {
  it("reads the total in words, then every state that is not done (F2)", () => {
    expect(countsText(counts())).toBe("16 runs · 2 running · 1 failed");
    expect(countsText(counts({ running: 0, failed: 0, waiting: 3, stuck: 1 }))).toBe("16 runs · 3 waiting · 1 stuck");
    expect(countsText(counts({ total: 1, running: 1, failed: 0, done: 0 }))).toBe("1 run · 1 running");
  });

  it("says a group whose runs all succeeded is all succeeded (F2)", () => {
    expect(countsText(counts({ total: 4, running: 0, failed: 0, done: 4 }))).toBe("4 runs · all succeeded");
    expect(countParts(counts({ total: 4, running: 0, failed: 0, done: 4 })).map((p) => p.tone)).toEqual(["total", "done"]);
  });

  it("reads `5 of 16` when the filters leave part of the group (F1)", () => {
    expect(countsText(counts({ total: 5 }), 16)).toBe("5 of 16 runs · 2 running · 1 failed");
    expect(countsText(counts({ total: 1, running: 0, failed: 0, done: 1 }), 3)).toBe("1 of 3 runs · all succeeded");
    // No filter (or a server without the field): the plain count.
    expect(countsText(counts(), 16)).toBe("16 runs · 2 running · 1 failed");
    expect(countsText(counts(), undefined)).toBe("16 runs · 2 running · 1 failed");
  });

  it("tags each part with its state, so it can be coloured", () => {
    expect(countParts(counts()).map((p) => p.tone)).toEqual(["total", "running", "failed"]);
  });

  it("says the counts in words for a screen reader", () => {
    expect(spokenCounts(counts())).toBe("16 runs, 2 running, 1 failed");
    expect(spokenCounts(counts({ total: 1, running: 0, failed: 0 }))).toBe("1 run, all succeeded");
    expect(spokenCounts(counts({ total: 5 }), 16)).toBe("5 of 16 runs, 2 running, 1 failed");
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
