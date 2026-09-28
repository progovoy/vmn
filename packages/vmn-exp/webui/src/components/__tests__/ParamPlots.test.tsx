import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import ParamPlots from "../ParamPlots";
import type { ExperimentRow } from "../../types";

const row = (i: number, metrics: Record<string, number | null>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", user_meta: null, metrics: metrics as Record<string, number>,
});

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("ParamPlots", () => {
  it("draws one canvas chart per metric with more than one value", async () => {
    const rows = [row(1, { loss: 0.5, acc: 0.1 }), row(2, { loss: 0.4 })];
    render(<ParamPlots rows={rows} metricCols={["loss", "acc"]} schema={null} />);
    expect(screen.getByText("loss")).toBeInTheDocument();
    expect(screen.queryByText("acc")).toBeNull();
    await waitFor(() => expect(instances).toHaveLength(1));
  });

  it("downsamples thousands of runs to at most 200 points per chart", async () => {
    const rows = Array.from({ length: 5000 }, (_, i) => row(i + 1, { loss: Math.sin(i) }));
    render(<ParamPlots rows={rows} metricCols={["loss"]} schema={null} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    const [, [xs]] = instances[0].data as [null, [Float64Array, Float64Array]];
    expect(xs.length).toBeLessThanOrEqual(200);
    expect(xs[0]).toBe(1);
    expect(xs[xs.length - 1]).toBe(5000);
  });

  it("shows the best value per the metric's goal", () => {
    const rows = [row(1, { loss: 0.5 }), row(2, { loss: 0.2 }), row(3, { loss: 0.9 })];
    render(<ParamPlots rows={rows} metricCols={["loss"]} schema={{ loss: { goal: "min" } }} />);
    expect(screen.getByText("best 0.2")).toBeInTheDocument();
  });

  it("does not rebuild the chart when re-rendered with the same props", async () => {
    const rows = [row(1, { loss: 0.5 }), row(2, { loss: 0.4 })];
    const cols = ["loss"];
    const { rerender } = render(<ParamPlots rows={rows} metricCols={cols} schema={null} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    rerender(<ParamPlots rows={rows} metricCols={cols} schema={null} />);
    expect(instances).toHaveLength(1);
    expect(instances[0].setData).not.toHaveBeenCalled();
  });
});
