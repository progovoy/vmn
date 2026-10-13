/** Parallel-coordinates brushes as a query (plan 23 W4): the clause the
 *  Runs tab's filter takes, matching exactly the brushed runs. */
import { describe, it, expect } from "vitest";
import type { ExperimentRow } from "../../types";
import { buildAxes, type Brushes } from "../parallelData";
import { brushQuery, fieldPath } from "../brushQuery";

const row = (i: number, metrics: Record<string, number>, params: Record<string, unknown>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: null,
  base_version: null, metrics, params,
});

const ROWS = [
  row(1, { loss: 0.5 }, { lr: 0.01, opt: "adam" }),
  row(2, { loss: 0.3 }, { lr: 0.001, opt: "sgd" }),
  row(3, { loss: 0.7 }, { lr: 0.1, opt: "adam" }),
];
const DIMS = ["loss", "lr", "opt"];
const AXES = buildAxes(ROWS, DIMS, ["loss"]);

describe("fieldPath", () => {
  it("leaves plain names bare and quotes the rest", () => {
    expect(fieldPath("metrics", "val_loss")).toBe("metrics.val_loss");
    expect(fieldPath("params", "train/lr")).toBe('params."train/lr"');
    expect(fieldPath("params", "a.b")).toBe('params."a.b"');
  });
});

describe("brushQuery", () => {
  it("is null without a brush", () => {
    expect(brushQuery(ROWS, AXES, ["loss"], new Map())).toBeNull();
  });

  it("bounds a numeric axis by the brushed runs' own values", () => {
    // t 0.4..1 on loss (0.3..0.7) holds 0.5 and 0.7.
    const b: Brushes = new Map([[0, [1, 0.4]]]);
    expect(brushQuery(ROWS, AXES, ["loss"], b)).toBe("metrics.loss >= 0.5 and metrics.loss <= 0.7");
  });

  it("writes bools bare and numbers on a mixed axis unquoted", () => {
    const rows = [row(1, {}, { cache: true }), row(2, {}, { cache: "auto" }), row(3, {}, { cache: 4 })];
    const axes = buildAxes(rows, ["cache"], []);
    // categories sorted: [4, auto, true]; t 0..1 holds all.
    const b: Brushes = new Map([[0, [0, 1]]]);
    expect(brushQuery(rows, axes, [], b)).toBe('params.cache in (true, "auto", 4)');
  });

  it("lists a categorical axis' brushed values, and ANDs the axes", () => {
    // opt categories [adam, sgd]: t 0 = adam only.
    const b: Brushes = new Map([[2, [0, 0.2]], [1, [0, 1]]]);
    expect(brushQuery(ROWS, AXES, ["loss"], b))
      .toBe('params.lr >= 0.001 and params.lr <= 0.1 and params.opt in ("adam")');
  });

  it("is null when a brush holds no run (nothing to show)", () => {
    const b: Brushes = new Map([[0, [0.55, 0.6]]]);
    expect(brushQuery(ROWS, AXES, ["loss"], b)).toBeNull();
  });
});
