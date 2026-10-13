import { describe, it, expect } from "vitest";
import { MAX_DEFAULT_PARAMS, goalMetrics, paramBudget, variedParams } from "../defaultColumns";
import type { ExperimentRow, MetricsSchema } from "../../types";

const row = (i: number, params: Record<string, unknown>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params, metrics: {},
});

describe("goalMetrics", () => {
  it("keeps the metrics the schema declares a goal for, in column order", () => {
    const schema: MetricsSchema = { val_acc: { goal: "max" }, val_loss: { goal: "min" }, grad: { hidden: true } };
    expect(goalMetrics(["loss", "val_loss", "grad", "val_acc"], schema)).toEqual(["val_loss", "val_acc"]);
  });

  it("never infers a goal from a name: only declared goals count", () => {
    expect(goalMetrics(["loss", "acc"], null)).toEqual([]);
    expect(goalMetrics(["loss"], { loss: {} })).toEqual([]);
  });
});

describe("variedParams", () => {
  it("leaves out a param every loaded row gives the same value", () => {
    const rows = [row(1, { lr: 0.1, seed: 7 }), row(2, { lr: 0.2, seed: 7 })];
    expect(variedParams(rows, ["lr", "seed"])).toEqual(["lr"]);
  });

  it("counts a param set on only one row as constant", () => {
    const rows = [row(1, { lr: 0.1, hp_0: 3 }), row(2, { lr: 0.2 })];
    expect(variedParams(rows, ["hp_0", "lr"])).toEqual(["lr"]);
  });

  it("compares values structurally, so equal lists are one value", () => {
    const rows = [row(1, { dims: [1, 2], opt: "adam" }), row(2, { dims: [1, 2], opt: "sgd" })];
    expect(variedParams(rows, ["dims", "opt"])).toEqual(["opt"]);
  });

  it("ranks the params most rows carry first", () => {
    const rows = [
      row(1, { a: 1, b: 1 }), row(2, { a: 2, b: 2 }), row(3, { b: 3 }),
    ];
    expect(variedParams(rows, ["a", "b"])).toEqual(["b", "a"]);
  });

  it("keeps every param while there is only one row to compare", () => {
    expect(variedParams([row(1, { lr: 0.1, seed: 1 })], ["lr", "seed"])).toEqual(["lr", "seed"]);
  });
});

describe("paramBudget", () => {
  it("allows the most default params when the table width is not known yet", () => {
    expect(paramBudget(0, 600)).toBe(MAX_DEFAULT_PARAMS);
    expect(MAX_DEFAULT_PARAMS).toBe(6);
  });

  it("allows as many params as fit beside the other columns, never more than six", () => {
    expect(paramBudget(1000, 760)).toBe(2);
    expect(paramBudget(5000, 760)).toBe(6);
    expect(paramBudget(900, 950)).toBe(0);
  });
});
