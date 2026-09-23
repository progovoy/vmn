import { describe, it, expect } from "vitest";
import { ema } from "../hooks/useSmoothing";
import {
  buildRows, capSeries, overlayRows, runOrigin, smoothRows, splitSysMetrics,
} from "../util/chartData";
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

  it("buildRows keeps sparse points of every metric", () => {
    const rows = buildRows({ loss: loss.slice(0, 300), val_loss: valLoss }, ["loss", "val_loss"], "step");
    const withVal = rows.filter((r) => typeof r.val_loss === "number");
    expect(withVal.map((r) => r.x)).toEqual([0, 100, 200]);
  });

  it("uses time, not the array index, for step-less samples", () => {
    const t0 = Date.UTC(2026, 0, 1, 0, 0, 0);
    const sys = [0, 1, 2].map((i) => pt(null, 10 + i, new Date(t0 + i * 30_000).toISOString()));
    const rows = buildRows({ sys_cpu_percent: sys }, ["sys_cpu_percent"], "relative", t0);
    expect(rows.map((r) => r.x)).toEqual([0, 30, 60]);
  });

  it("splitSysMetrics separates sys_* metrics", () => {
    expect(splitSysMetrics(["loss", "sys_rss_mb", "acc"])).toEqual({
      training: ["loss", "acc"], system: ["sys_rss_mb"],
    });
  });

  it("smoothRows smooths each key over its own points only", () => {
    const rows = [{ x: 0, a: 2 }, { x: 1 }, { x: 2, a: 4 }] as Record<string, number>[];
    const sm = smoothRows(rows, ["a"], 0.5);
    expect(sm[0].a__smooth).toBe(2);
    expect(sm[1].a__smooth).toBeUndefined();
    expect(sm[2].a__smooth).toBeCloseTo(3);
  });
});

describe("overlay", () => {
  it("relative time starts at each run's own origin", () => {
    const a0 = Date.UTC(2026, 0, 1, 0, 0, 0);
    const b0 = Date.UTC(2026, 0, 2, 0, 0, 0);
    const mk = (t0: number) => [0, 1].map((i) => pt(i, i, new Date(t0 + i * 10_000).toISOString()));
    const runs = [
      { key: "a", series: { loss: mk(a0) } },
      { key: "b", series: { loss: mk(b0) } },
    ];
    const rows = overlayRows("loss", runs.map((r) => ({ ...r, origin: runOrigin(r.series) })), "relative");
    expect(rows.map((r) => r.x)).toEqual([0, 10]);
    expect(rows[0].a).toBe(0);
    expect(rows[0].b).toBe(0);
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
