import { describe, it, expect } from "vitest";
import type { FleetChild } from "../../types";
import {
  bestOf, childProgress, fleetLabel, fleetMetric, fleetRowsOf, sortRows, varyingParams, type FleetRow,
} from "../fleetRows";

function child(n: number, extra: Partial<FleetChild> = {}): FleetChild {
  return {
    verstr: `0.0.1-dev.c${n}`, status: "succeeded", progress: null, progress_total: null,
    idx: n, name: `run${n}`, params: {}, metrics: {}, ...extra,
  };
}

const row = (verstr: string, value: number | null, extra: Partial<FleetRow> = {}): FleetRow => ({
  verstr, label: verstr, status: "succeeded", params: {}, value, progress: null, ...extra,
});

describe("fleetLabel", () => {
  it("reads @N name, @N, the name, else the verstr", () => {
    expect(fleetLabel({ verstr: "v", idx: 3, name: "a" })).toBe("@3 a");
    expect(fleetLabel({ verstr: "v", idx: 3, name: null })).toBe("@3");
    expect(fleetLabel({ verstr: "v", name: "a" })).toBe("a");
    expect(fleetLabel({ verstr: "v" })).toBe("v");
  });
});

describe("childProgress", () => {
  it("is last_step/of when the total is known", () => {
    expect(childProgress(child(1, { last_step: { step: 3, of: 10 } }))).toEqual({ step: 3, of: 10 });
  });

  it("falls back to the logged progress/progress_total", () => {
    expect(childProgress(child(1, { progress: 7, progress_total: 20 }))).toEqual({ step: 7, of: 20 });
  });

  it("is null without a total", () => {
    expect(childProgress(child(1, { last_step: { step: 3, of: null } }))).toBeNull();
    expect(childProgress(child(1))).toBeNull();
  });
});

describe("varyingParams", () => {
  it("keeps only params whose values differ among the rows, preferred ones first", () => {
    const rows = [
      row("a", null, { params: { lr: 0.1, bs: 16, opt: "adam" } }),
      row("b", null, { params: { lr: 0.2, bs: 16, opt: "sgd" } }),
    ];
    expect(varyingParams(rows)).toEqual(["lr", "opt"]);
    expect(varyingParams(rows, ["opt"])).toEqual(["opt", "lr"]);
  });

  it("counts a missing value as a value and caps the list", () => {
    const rows = [row("a", null, { params: { x: 1 } }), row("b", null)];
    expect(varyingParams(rows)).toEqual(["x"]);
    const many = [row("a", null, { params: Object.fromEntries([..."abcdefgh"].map((k) => [k, 1])) }), row("b", null)];
    expect(varyingParams(many)).toHaveLength(6);
  });
});

describe("fleetMetric", () => {
  it("prefers the schema's primary metric, then a metric with a goal", () => {
    const children = [child(1, { metrics: { acc: 0.9, loss: 0.2, lr: 0.1 } })];
    expect(fleetMetric(children, { acc: { primary: true } })).toEqual({ name: "acc", goal: "max" });
    expect(fleetMetric(children, null)).toEqual({ name: "acc", goal: "max" });
  });

  it("is null when no child metric has a goal", () => {
    expect(fleetMetric([child(1, { metrics: { lr: 0.1, foo: 2 } })], null)).toBeNull();
  });

  it("leaves out params folded into metrics", () => {
    expect(fleetMetric([child(1, { params: { score: 1 }, metrics: { score: 1 } })], null)).toBeNull();
  });
});

describe("fleetRowsOf", () => {
  it("labels each child and takes the metric's value", () => {
    const [r] = fleetRowsOf([child(4, { metrics: { loss: 0.5 } })], { name: "loss", goal: "min" });
    expect(r).toMatchObject({ verstr: "0.0.1-dev.c4", label: "@4 run4", value: 0.5 });
  });
});

describe("sortRows", () => {
  const rows = [row("a", 0.5), row("b", null), row("c", 0.1), row("d", 0.9)];

  it("sorts by value both ways with missing values last", () => {
    expect(sortRows(rows, "value", "asc").map((r) => r.verstr)).toEqual(["c", "a", "d", "b"]);
    expect(sortRows(rows, "value", "desc").map((r) => r.verstr)).toEqual(["d", "a", "c", "b"]);
  });

  it("sorts by a param and by the label", () => {
    const p = [row("a", null, { params: { lr: 0.3 } }), row("b", null, { params: { lr: 0.1 } })];
    expect(sortRows(p, "p:lr", "asc").map((r) => r.verstr)).toEqual(["b", "a"]);
    expect(sortRows(rows, "label", "desc").map((r) => r.verstr)).toEqual(["d", "c", "b", "a"]);
  });
});

describe("bestOf", () => {
  it("is the best value toward the goal, none without a goal", () => {
    const rows = [row("a", 0.5), row("b", null), row("c", 0.1)];
    expect(bestOf(rows, "min")).toBe("c");
    expect(bestOf(rows, "max")).toBe("a");
    expect(bestOf(rows, null)).toBeNull();
  });
});
