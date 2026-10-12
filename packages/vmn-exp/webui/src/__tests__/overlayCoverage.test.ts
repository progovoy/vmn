import { describe, it, expect } from "vitest";
import type { OverlayRunData } from "../pages/overlaySeries";
import {
  curvelessRuns, metricCurves, noCurvesNote, runLabel, unionMetrics,
} from "../pages/overlayCoverage";
import type { SeriesPoint } from "../types";

const pts = (n: number, x?: number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: i, ts: null, ...(x == null ? {} : { x: x + i }) }));

function run(key: string, series: Record<string, SeriesPoint[]>, extra: Partial<OverlayRunData> = {}): OverlayRunData {
  return { key, series, origin: 0, status: null, heartbeatSec: null, ...extra };
}

const a = run("a", { loss: pts(3), acc: pts(3) });
const b = run("b", { loss: pts(3), lr: pts(1) });
const outer = run("o", {}, { idx: 36, name: "lr_layers_grid", kind: "outer", children: ["t1", "t2"] });

describe("unionMetrics", () => {
  it("lists every metric with a curve in at least one run, sorted", () => {
    expect(unionMetrics([a, b, outer])).toEqual(["acc", "loss"]);
  });

  it("is empty when no run has a curve", () => {
    expect(unionMetrics([outer, run("x", { lr: pts(1) })])).toEqual([]);
  });
});

describe("curvelessRuns", () => {
  it("names the runs with no curve at all", () => {
    expect(curvelessRuns([a, b, outer]).map((r) => r.key)).toEqual(["o"]);
  });
});

describe("runLabel", () => {
  it("prefers @idx and name, then @idx, then the verstr", () => {
    expect(runLabel(outer)).toBe("@36 lr_layers_grid");
    expect(runLabel(run("v", {}, { idx: 4 }))).toBe("@4");
    expect(runLabel(run("0.0.1-dev.x", {}))).toBe("0.0.1-dev.x");
  });
});

describe("noCurvesNote", () => {
  it("names curveless runs, calling out sweep (outer) runs only", () => {
    const plain = run("0.0.1-dev.p", {}, { kind: "single" });
    expect(noCurvesNote([a, outer, plain])).toBe(
      "No curves: @36 lr_layers_grid (sweep run; its trials log the curves), 0.0.1-dev.p",
    );
  });

  it("is null when every run has curves", () => {
    expect(noCurvesNote([a, b])).toBeNull();
  });
});

describe("metricCurves", () => {
  it("plots only the runs that have the metric", () => {
    const got = metricCurves("acc", [a, b, outer], null, null);
    expect(got.xMetric).toBeNull();
    expect(got.curves.map((c) => c.key)).toEqual(["a"]);
  });

  it("leaves out a run whose only point would be an unlisted dot", () => {
    const dot = run("d", { loss: pts(1) });
    expect(curvelessRuns([a, dot]).map((r) => r.key)).toEqual(["d"]);
    expect(metricCurves("loss", [a, dot], null, null).curves.map((c) => c.key)).toEqual(["a"]);
  });

  it("keeps the chart on the x metric for the runs that have it joined", () => {
    const joined = { a: { loss: pts(3, 10) }, b: { loss: [] } };
    const got = metricCurves("loss", [a, b, outer], "epoch", joined);
    expect(got.xMetric).toBe("epoch");
    expect(got.curves.map((c) => c.key)).toEqual(["a"]);
    expect(got.curves[0].points[0].x).toBe(10);
  });

  it("falls back to the step axis when no run has the x metric", () => {
    const got = metricCurves("loss", [a, b], "epoch", { a: {}, b: { loss: [] } });
    expect(got.xMetric).toBeNull();
    expect(got.curves.map((c) => c.key)).toEqual(["a", "b"]);
  });

  it("uses the plain series until the join arrives", () => {
    const got = metricCurves("loss", [a, b], "epoch", null);
    expect(got.xMetric).toBeNull();
    expect(got.curves.map((c) => c.key)).toEqual(["a", "b"]);
  });
});
