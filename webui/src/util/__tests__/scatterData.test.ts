import { describe, it, expect } from "vitest";
import { nearestPoint, scatterGroups } from "../scatterData";
import type { ExperimentRow } from "../../types";

const row = (i: number, metrics: Record<string, number | null>, params: Record<string, unknown> = {}): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null, branch: "main",
  base_version: "0.0.1", user_meta: null, params, metrics: metrics as Record<string, number>,
});

describe("scatterGroups", () => {
  const rows = [row(1, { a: 1, b: 5 }), row(2, { a: 2, b: 9 }), row(3, { a: 3, b: null }), row(4, { a: 4, b: 9 })];

  it("splits plottable rows into rest and best (by the y goal)", () => {
    const { rest, best } = scatterGroups(rows, "a", "b", [], "max");
    expect([...rest.xs]).toEqual([1]);
    expect([...best.xs]).toEqual([2, 4]);
    expect(best.verstrs).toEqual(["v2", "v4"]);
    expect(best.idxs).toEqual([2, 4]);
  });

  it("picks the minimum for a min goal", () => {
    const { best } = scatterGroups(rows, "a", "b", [], "min");
    expect([...best.ys]).toEqual([5]);
  });

  it("reads params from row.params", () => {
    const { rest, best } = scatterGroups([row(1, { b: 1 }, { lr: 0.1 }), row(2, { b: 2 }, { lr: 0.2 })], "lr", "b", ["lr"], "max");
    expect([...rest.xs, ...best.xs].sort()).toEqual([0.1, 0.2]);
  });
});

describe("nearestPoint", () => {
  const { rest, best } = scatterGroups(
    [row(1, { a: 0, b: 0 }), row(2, { a: 10, b: 100 }), row(3, { a: 5, b: 50 })], "a", "b", [], "max",
  );

  it("finds the closest point across groups, measured relative to each axis span", () => {
    expect(nearestPoint([rest, best], 4.9, 51, 0.05)?.verstr).toBe("v3");
    expect(nearestPoint([rest, best], 9.8, 99, 0.05)?.verstr).toBe("v2");
  });

  it("is null when no point is within the radius", () => {
    expect(nearestPoint([rest, best], 2.5, 25, 0.05)).toBeNull();
  });

  it("is null for no points", () => {
    const empty = scatterGroups([], "a", "b", [], "max");
    expect(nearestPoint([empty.rest, empty.best], 0, 0, 0.05)).toBeNull();
  });
});
