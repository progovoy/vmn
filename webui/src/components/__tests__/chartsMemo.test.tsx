import { describe, it, expect, beforeAll } from "vitest";
import { render } from "@testing-library/react";
import CurveChart from "../CurveChart";
import GroupedMetrics from "../GroupedMetrics";
import MetricBarChart from "../MetricBarChart";
import MetricScatter from "../MetricScatter";
import ParamPlots from "../ParamPlots";
import ParallelCoordinates from "../ParallelCoordinates";
import TrainingCurves from "../TrainingCurves";
import type { ExperimentRow } from "../../types";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const MEMO = Symbol.for("react.memo");

describe("chart components are memoized", () => {
  it.each([
    ["CurveChart", CurveChart], ["GroupedMetrics", GroupedMetrics],
    ["MetricBarChart", MetricBarChart], ["MetricScatter", MetricScatter],
    ["ParamPlots", ParamPlots], ["ParallelCoordinates", ParallelCoordinates],
    ["TrainingCurves", TrainingCurves],
  ])("%s", (_name, component) => {
    expect((component as unknown as { $$typeof: symbol }).$$typeof).toBe(MEMO);
  });
});

const row = (i: number, metrics: Record<string, number>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: i % 2 ? "main" : "dev", base_version: "0.0.1", user_meta: null, metrics,
});
const ROWS = [row(1, { loss: 0.5, acc: 0.1 }), row(2, { loss: 0.4, acc: 0.2 })];

function axisStrokes(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".recharts-cartesian-axis-line")]
    .map((el) => el.getAttribute("stroke") ?? "");
}

describe("axes take their colour from the theme", () => {
  it.each([
    ["MetricBarChart", () => <MetricBarChart rows={ROWS} metricCols={["loss"]} schema={null} />],
    ["MetricScatter", () => <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />],
    ["GroupedMetrics", () => <GroupedMetrics rows={ROWS} metricCols={["loss"]} paramCols={[]} schema={null} />],
  ])("%s", (_name, el) => {
    const { container } = render(el());
    const strokes = axisStrokes(container);
    expect(strokes.length).toBeGreaterThan(0);
    for (const s of strokes) expect(s).toBe("var(--text-3)");
  });
});
