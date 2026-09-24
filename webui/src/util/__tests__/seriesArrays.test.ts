import { describe, it, expect } from "vitest";
import {
  emaXY, filterMetrics, nearestIndex, toXY, tooltipRows,
} from "../seriesArrays";
import { runOrigin } from "../chartData";
import type { SeriesPoint } from "../../types";

const pt = (step: number | null, value: number, ts: string | null = null): SeriesPoint =>
  ({ step, value, ts });

describe("toXY", () => {
  it("builds typed x/y arrays by step", () => {
    const { xs, ys } = toXY([pt(0, 1), pt(1, 2), pt(2, 3)], "step", NaN);
    expect(xs).toBeInstanceOf(Float64Array);
    expect(ys).toBeInstanceOf(Float64Array);
    expect([...xs]).toEqual([0, 1, 2]);
    expect([...ys]).toEqual([1, 2, 3]);
  });

  it("drops non-finite values instead of plotting them", () => {
    const pts = [pt(0, 1), pt(1, null as unknown as number), pt(2, NaN), pt(3, 4)];
    const { xs, ys } = toXY(pts, "step", NaN);
    expect([...xs]).toEqual([0, 3]);
    expect([...ys]).toEqual([1, 4]);
  });

  it("places points by seconds since the origin in relative mode", () => {
    const t0 = Date.UTC(2026, 0, 1);
    const iso = (s: number) => new Date(t0 + s * 1000).toISOString();
    const { xs } = toXY([pt(5, 1, iso(0)), pt(6, 1, iso(30))], "relative", t0);
    expect([...xs]).toEqual([0, 30]);
  });

  it("sorts points by x so the line never doubles back", () => {
    const { xs, ys } = toXY([pt(2, 20), pt(0, 0), pt(1, 10)], "step", NaN);
    expect([...xs]).toEqual([0, 1, 2]);
    expect([...ys]).toEqual([0, 10, 20]);
  });

  it("keeps only positive values for a log axis", () => {
    const { xs } = toXY([pt(0, 0), pt(1, -1), pt(2, 0.5)], "step", NaN, { positiveOnly: true });
    expect([...xs]).toEqual([2]);
  });
});

describe("emaXY", () => {
  it("returns the input unchanged when alpha is 0", () => {
    const ys = Float64Array.from([1, 2, 3]);
    expect(emaXY(ys, 0)).toBe(ys);
  });

  it("smooths with an exponential moving average", () => {
    const out = emaXY(Float64Array.from([2, 4]), 0.5);
    expect(out[0]).toBe(2);
    expect(out[1]).toBeCloseTo(3);
  });
});

describe("nearestIndex", () => {
  const xs = Float64Array.from([0, 10, 20, 30]);
  it("finds the closest x by binary search", () => {
    expect(nearestIndex(xs, 14)).toBe(1);
    expect(nearestIndex(xs, 16)).toBe(2);
    expect(nearestIndex(xs, -5)).toBe(0);
    expect(nearestIndex(xs, 99)).toBe(3);
  });
  it("is -1 for an empty series", () => {
    expect(nearestIndex(new Float64Array(0), 3)).toBe(-1);
  });
});

describe("tooltipRows", () => {
  const mk = (key: string, v: number) => ({
    key, xs: Float64Array.from([0, 1, 2]), ys: Float64Array.from([v, v, v]),
  });
  const series = [mk("a", 1), mk("b", 5), mk("c", 3), mk("d", 10)];

  it("sorts rows by value, largest first", () => {
    expect(tooltipRows(series, 1, null, 10).map((r) => r.key)).toEqual(["d", "b", "c", "a"]);
  });

  it("keeps the rows nearest the cursor's y when over the limit", () => {
    const rows = tooltipRows(series, 1, 4, 2);
    expect(rows.map((r) => r.key)).toEqual(["b", "c"]);
  });

  it("reports the x and value of each series' nearest point", () => {
    const [row] = tooltipRows([{ key: "a", xs: Float64Array.from([0, 10]), ys: Float64Array.from([1, 2]) }], 8, null, 5);
    expect(row).toEqual({ key: "a", x: 10, value: 2 });
  });

  it("skips empty series", () => {
    expect(tooltipRows([{ key: "a", xs: new Float64Array(0), ys: new Float64Array(0) }], 1, null, 5)).toEqual([]);
  });
});

describe("filterMetrics", () => {
  it("matches case-insensitive substrings", () => {
    expect(filterMetrics(["loss", "val_loss", "acc"], "LOSS")).toEqual(["loss", "val_loss"]);
  });
  it("keeps everything for an empty query", () => {
    expect(filterMetrics(["loss", "acc"], "  ")).toEqual(["loss", "acc"]);
  });
});

describe("toXY time axes", () => {
  it("places step-less samples by time, not by array index", () => {
    const t0 = Date.UTC(2026, 0, 1, 0, 0, 0);
    const sys = [0, 1, 2].map((i) => pt(null, 10 + i, new Date(t0 + i * 30_000).toISOString()));
    expect([...toXY(sys, "step", t0).xs]).toEqual([0, 30, 60]);
  });

  it("measures relative time from each run's own origin", () => {
    const mk = (t0: number) => [0, 1].map((i) => pt(i, i, new Date(t0 + i * 10_000).toISOString()));
    const a = mk(Date.UTC(2026, 0, 1, 0, 0, 0));
    const b = mk(Date.UTC(2026, 0, 2, 0, 0, 0));
    const xa = toXY(a, "relative", runOrigin({ loss: a })).xs;
    const xb = toXY(b, "relative", runOrigin({ loss: b })).xs;
    expect([...xa]).toEqual([0, 10]);
    expect([...xb]).toEqual([0, 10]);
  });
});
