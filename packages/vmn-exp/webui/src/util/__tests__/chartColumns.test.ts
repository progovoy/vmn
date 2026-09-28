import { describe, it, expect } from "vitest";
import { chartKeys, columnsToRows } from "../chartColumns";

describe("chartKeys", () => {
  it("asks trend and bar charts for metrics only", () => {
    expect(chartKeys("trend", ["loss", "acc"], ["lr"])).toEqual(["metrics.loss", "metrics.acc"]);
    expect(chartKeys("bar", ["loss"], ["lr"])).toEqual(["metrics.loss"]);
  });

  it("adds params for the charts that plot them, and branch for grouping", () => {
    expect(chartKeys("scatter", ["loss"], ["lr"])).toEqual(["metrics.loss", "params.lr"]);
    expect(chartKeys("parallel", ["loss"], ["lr"])).toEqual(["metrics.loss", "params.lr"]);
    expect(chartKeys("grouped", ["loss"], ["lr"])).toEqual(["metrics.loss", "params.lr", "branch"]);
  });
});

describe("columnsToRows", () => {
  it("turns aligned columns into chart rows", () => {
    const rows = columnsToRows({
      verstrs: ["a", "b"],
      idx: [1, 2],
      columns: {
        "metrics.loss": [0.5, null],
        "params.opt": ["adam", "sgd"],
        branch: ["main", "feat"],
      },
      total: 2,
    });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      verstr: "a", idx: 1, branch: "main", metrics: { loss: 0.5 }, params: { opt: "adam" },
    });
    // A run with no value for a key simply lacks it — charts skip it.
    expect(rows[1].metrics).toEqual({});
    expect(rows[1].params).toEqual({ opt: "sgd" });
  });

  it("keeps only numbers in metrics", () => {
    const rows = columnsToRows({
      verstrs: ["a"], idx: [3], columns: { "metrics.x": ["oops"] }, total: 1,
    });
    expect(rows[0].metrics).toEqual({});
  });
});
