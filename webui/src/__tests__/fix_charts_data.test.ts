import { describe, it, expect } from "vitest";
import { ema } from "../hooks/useSmoothing";
import { splitSysMetrics } from "../util/chartData";
import { maxOf, minOf } from "../util/stats";
import { paramValue, runColor } from "../util";

describe("ema skips gaps", () => {
  it("does not propagate NaN past a missing value", () => {
    const out = ema([1, undefined, 2, 3] as unknown as number[], 0.5);
    expect(out[0]).toBe(1);
    expect(out[1]).toBeUndefined();
    expect(out[2]).toBeCloseTo(1.5);
    expect(out[3]).toBeCloseTo(2.25);
  });

  it("treats null and NaN as gaps too", () => {
    const out = ema([null, 4, NaN, 8] as unknown as number[], 0.5);
    expect(out[0]).toBeUndefined();
    expect(out[1]).toBe(4);
    expect(out[2]).toBeUndefined();
    expect(out[3]).toBeCloseTo(6);
  });
});

describe("per-metric series", () => {
  it("splitSysMetrics separates sys_* metrics", () => {
    expect(splitSysMetrics(["loss", "sys_rss_mb", "acc"])).toEqual({
      training: ["loss", "acc"], system: ["sys_rss_mb"],
    });
  });
});

describe("helpers", () => {
  it("minOf/maxOf handle huge arrays and skip gaps", () => {
    const big = Array.from({ length: 200_000 }, (_, i) => i);
    expect(minOf(big)).toBe(0);
    expect(maxOf(big)).toBe(199_999);
    expect(minOf([NaN, 3, null as unknown as number, 2])).toBe(2);
    expect(Number.isNaN(minOf([]))).toBe(true);
  });

  it("runColor gives distinct colours well beyond six runs", () => {
    const colours = new Set(Array.from({ length: 30 }, (_, i) => runColor(i)));
    expect(colours.size).toBe(30);
  });

  it("paramValue prefers params over user_meta", () => {
    expect(paramValue({ params: { lr: 0.1 }, user_meta: { lr: 9 } }, "lr")).toBe(0.1);
    expect(paramValue({ params: {}, user_meta: { lr: 9 } }, "lr")).toBe(9);
    expect(paramValue({ user_meta: null }, "lr")).toBeUndefined();
  });
});
