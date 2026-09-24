import { describe, it, expect } from "vitest";
import {
  axisT, buildAxes, buildMatrix, colorScale, selectRows, targetTs, tFromY, yFromT,
} from "../parallelData";
import { resolveCssColor } from "../cssColor";
import type { ExperimentRow } from "../../types";

function row(i: number, metrics: Record<string, number | null>, params: Record<string, unknown> = {}): ExperimentRow {
  return {
    idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", user_meta: null, params,
    metrics: metrics as Record<string, number>,
  };
}

const ROWS = [
  row(1, { loss: 0.5 }, { model: "vit", lr: 0.1, aug: true }),
  row(2, { loss: 0.3 }, { model: "resnet", lr: 0.01, aug: false }),
  row(3, { loss: null }, { model: "vit", lr: "auto" }),
];

describe("buildAxes", () => {
  it("makes a numeric axis over the finite values", () => {
    const [loss] = buildAxes(ROWS, ["loss"], ["loss"]);
    expect(loss).toEqual({ kind: "num", name: "loss", min: 0.3, max: 0.5 });
  });

  it("turns string and boolean params into sorted categorical axes", () => {
    const [model, aug] = buildAxes(ROWS, ["model", "aug"], []);
    expect(model).toEqual({ kind: "cat", name: "model", categories: ["resnet", "vit"] });
    expect(aug).toEqual({ kind: "cat", name: "aug", categories: ["false", "true"] });
  });

  it("makes a mixed number/string param categorical rather than dropping it", () => {
    const [lr] = buildAxes(ROWS, ["lr"], []);
    expect(lr.kind).toBe("cat");
    expect(lr.kind === "cat" && lr.categories).toEqual(["0.01", "0.1", "auto"]);
  });
});

describe("axisT", () => {
  it("places numbers linearly and categories evenly, missing values as null", () => {
    expect(axisT({ kind: "num", name: "a", min: 0, max: 4 }, 1)).toBe(0.25);
    expect(axisT({ kind: "num", name: "a", min: 2, max: 2 }, 2)).toBe(0.5);
    expect(axisT({ kind: "num", name: "a", min: 0, max: 4 }, null)).toBeNull();
    const cat = { kind: "cat" as const, name: "m", categories: ["a", "b", "c"] };
    expect(axisT(cat, "b")).toBe(0.5);
    expect(axisT(cat, "c")).toBe(1);
    expect(axisT(cat, undefined)).toBeNull();
    expect(axisT({ kind: "cat", name: "m", categories: ["x"] }, "x")).toBe(0.5);
  });
});

describe("buildMatrix + selectRows", () => {
  const dims = ["loss", "model"];
  const axes = buildAxes(ROWS, dims, ["loss"]);
  const m = buildMatrix(ROWS, dims, ["loss"], axes);

  it("stores one t per row and axis, NaN for a gap", () => {
    expect(Array.from(m.slice(0, 2))).toEqual([1, 1]);
    expect(Array.from(m.slice(2, 4))).toEqual([0, 0]);
    expect(Number.isNaN(m[4])).toBe(true);
  });

  it("is null without brushes and ANDs every active brush", () => {
    expect(selectRows(m, 2, new Map())).toBeNull();
    expect(selectRows(m, 2, new Map([[1, [0.9, 1] as [number, number]]]))).toEqual([0, 2]);
    expect(selectRows(m, 2, new Map([
      [1, [0.9, 1] as [number, number]],
      [0, [0.5, 1] as [number, number]],
    ]))).toEqual([0]);
  });
});

describe("pixel <-> t", () => {
  it("round-trips with t=1 at the top", () => {
    expect(yFromT(1, 20, 260)).toBe(20);
    expect(yFromT(0, 20, 260)).toBe(280);
    expect(tFromY(150, 20, 260)).toBe(0.5);
  });
});

describe("colour", () => {
  it("colorScale clamps and gives distinct ends", () => {
    expect(colorScale(0)).toMatch(/^rgb\(/);
    expect(colorScale(0)).not.toBe(colorScale(1));
    expect(colorScale(-3)).toBe(colorScale(0));
    expect(colorScale(9)).toBe(colorScale(1));
  });

  it("targetTs puts the best value at 1 whatever the goal", () => {
    const rows = [row(1, { loss: 0.5 }), row(2, { loss: 0.1 }), row(3, {})];
    expect(targetTs(rows, "loss", "min")).toEqual([0, 1, null]);
    expect(targetTs(rows, "loss", "max")).toEqual([1, 0, null]);
  });

  it("resolveCssColor follows var() chains and keeps plain colours", () => {
    const vars: Record<string, string> = { "--a": "var(--b)", "--b": " #123456 " };
    const read = (n: string) => vars[n] ?? "";
    expect(resolveCssColor("var(--a)", read)).toBe("#123456");
    expect(resolveCssColor("red", read)).toBe("red");
    expect(resolveCssColor("var(--missing)", read, "gray")).toBe("gray");
  });
});
