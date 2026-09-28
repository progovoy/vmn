import { describe, it, expect } from "vitest";
import type { SeriesPoint } from "../../types";
import { xOf } from "../chartData";
import { toXY } from "../seriesArrays";
import {
  AUTO_X, NO_X, chartPoints, chartXMetric, xMetricMap, xMetricOptions,
} from "../xMetric";

const p = (step: number, value: number, x?: number): SeriesPoint =>
  ({ step, ts: null, value, ...(x === undefined ? {} : { x }) });

describe("chartXMetric", () => {
  const declared = { val_loss: "epoch" };

  it("uses the declared step metric by default", () => {
    expect(chartXMetric("step", AUTO_X, "val_loss", declared)).toBe("epoch");
    expect(chartXMetric("step", AUTO_X, "loss", declared)).toBeNull();
  });

  it("a picked metric applies to every chart but its own", () => {
    expect(chartXMetric("step", "lr", "loss", declared)).toBe("lr");
    expect(chartXMetric("step", "lr", "lr", declared)).toBeNull();
  });

  it("none and the time modes ignore x metrics", () => {
    expect(chartXMetric("step", NO_X, "val_loss", declared)).toBeNull();
    expect(chartXMetric("wall", AUTO_X, "val_loss", declared)).toBeNull();
    expect(chartXMetric("relative", "lr", "loss", declared)).toBeNull();
  });

  it("xMetricMap lists only the charts that need a join", () => {
    expect(xMetricMap(["loss", "val_loss"], "step", AUTO_X, declared)).toEqual({ val_loss: "epoch" });
    expect(xMetricMap(["loss", "epoch"], "step", "epoch", {})).toEqual({ loss: "epoch" });
  });
});

describe("x metric data join", () => {
  const series = { loss: [p(0, 1), p(1, 0.5), p(2, 0.25)] };

  it("a joined chart plots against x and drops points without one", () => {
    const joined = { loss: [p(0, 1, 0), p(2, 0.25, 1)] };
    const { points, xMetric } = chartPoints(series, joined, "loss", { loss: "epoch" });
    expect(xMetric).toBe("epoch");
    const xy = toXY([...points, p(5, 9)], "metric", 0);
    expect(Array.from(xy.xs)).toEqual([0, 1]);
    expect(Array.from(xy.ys)).toEqual([1, 0.25]);
  });

  it("falls back to the step until the joined series arrives", () => {
    const { points, xMetric } = chartPoints(series, null, "loss", { loss: "epoch" });
    expect(xMetric).toBeNull();
    expect(points).toBe(series.loss);
  });

  it("xOf in metric mode reads the joined x", () => {
    expect(xOf(p(3, 1, 0.5), 0, "metric", 0)).toBe(0.5);
    expect(xOf(p(3, 1), 0, "metric", 0)).toBeNull();
  });

  it("offers training metrics with data as x choices, sorted", () => {
    expect(xMetricOptions({ lr: [p(0, 1)], epoch: [p(0, 0)], sys_cpu: [p(0, 1)], empty: [] }))
      .toEqual(["epoch", "lr"]);
  });
});
