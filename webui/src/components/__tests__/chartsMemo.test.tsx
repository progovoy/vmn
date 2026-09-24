import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
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

describe("charts take their colours from the theme", () => {
  it.each([
    ["MetricBarChart", () => <MetricBarChart rows={ROWS} metricCols={["loss"]} schema={null} />],
    ["GroupedMetrics", () => <GroupedMetrics rows={ROWS} metricCols={["loss"]} paramCols={[]} schema={null} />],
  ])("%s uses CSS variables, not hard-coded colours", (_name, el) => {
    const { container } = render(el());
    expect(container.innerHTML).toContain("var(--");
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{6}/i);
  });
});

describe("GroupedMetrics chart", () => {
  it("draws one bar per group, sized by the group mean, with a ± std whisker", () => {
    const rows = [
      row(1, { loss: 0.2 }), row(3, { loss: 0.6 }), // main: mean 0.4, std 0.2
      row(2, { loss: 0.8 }), // dev: mean 0.8
    ];
    render(<GroupedMetrics rows={rows} metricCols={["loss"]} paramCols={[]} schema={null} />);
    const bars = screen.getAllByTestId("group-bar");
    expect(bars.map((b) => b.getAttribute("data-group"))).toEqual(["main", "dev"]);
    expect(bars[0].style.height).toBe("50%");
    expect(bars[1].style.height).toBe("100%");
    expect(screen.getAllByTestId("group-whisker")[0].style.height).toBe("50%");
    expect(bars[0].getAttribute("title")).toBe("main: 0.4 ± 0.2 (n=2)");
  });
});
