import { describe, it, expect } from "vitest";
import { ema } from "../hooks/useSmoothing";
import { capSeries, splitSysMetrics } from "../util/chartData";
import { maxOf, minOf } from "../util/stats";
import { paramValue, runColor } from "../util";
import type { SeriesPoint } from "../types";

const pt = (step: number | null, value: number, ts: string | null = null): SeriesPoint =>
  ({ step, value, ts });

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
  const loss = Array.from({ length: 5000 }, (_, i) => pt(i, 1 / (i + 1)));
  const valLoss = [0, 100, 200].map((s) => pt(s, 0.5));

  it("capSeries downsamples each metric on its own and keeps first/last", () => {
    const capped = capSeries({ loss, val_loss: valLoss }, 500);
    expect(capped.loss.length).toBeLessThanOrEqual(500);
    expect(capped.loss[0].step).toBe(0);
    expect(capped.loss[capped.loss.length - 1].step).toBe(4999);
    // the sparse series survives intact
    expect(capped.val_loss).toHaveLength(3);
  });

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
