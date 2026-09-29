import { describe, it, expect } from "vitest";
import { barPercent, valueMeans } from "../importanceData";
import type { ExperimentRow } from "../../types";

const row = (i: number, metrics: ExperimentRow["metrics"], params: Record<string, unknown>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: null,
  base_version: null, params, metrics,
});

describe("valueMeans", () => {
  it("averages the metric per param value, skipping runs missing either", () => {
    const rows = [
      row(1, { loss: 1 }, { opt: "sgd" }),
      row(2, { loss: 3 }, { opt: "sgd" }),
      row(3, { loss: 2 }, { opt: "adam" }),
      row(4, {}, { opt: "adam" }),
      row(5, { loss: 9 }, {}),
      row(6, { loss: 4 }, { opt: true }),
    ];
    expect(valueMeans(rows, "opt", "loss")).toEqual([
      { value: "adam", n: 1, mean: 2 },
      { value: "sgd", n: 2, mean: 2 },
      { value: "true", n: 1, mean: 4 },
    ]);
  });
});

describe("barPercent", () => {
  it("scales to the largest importance", () => {
    expect(barPercent(0.2, 0.8)).toBe(25);
    expect(barPercent(0.8, 0.8)).toBe(100);
    expect(barPercent(0, 0)).toBe(0);
  });
});
