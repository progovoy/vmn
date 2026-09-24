import { describe, it, expect, beforeAll, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("../components/__tests__/fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "../components/__tests__/fakeUPlot";
import MetricBarChart from "../components/MetricBarChart";
import MetricScatter from "../components/MetricScatter";
import GroupedMetrics from "../components/GroupedMetrics";
import ParallelCoordinates from "../components/ParallelCoordinates";
import type { ExperimentRow } from "../types";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

function row(i: number, metrics: Record<string, number | null>, params: Record<string, unknown> = {}): ExperimentRow {
  return {
    idx: i, verstr: `0.0.1-dev.${i}`, code_verstr: `0.0.1-dev.${i}`, timestamp: null,
    note: null, branch: "main", base_version: "0.0.1", user_meta: null, params,
    metrics: metrics as Record<string, number>,
  };
}

describe("MetricBarChart at scale", () => {
  it("caps the bars to the top 50 runs and says so", () => {
    const rows = Array.from({ length: 120 }, (_, i) => row(i + 1, { acc: i / 120 }));
    const { container } = render(<MetricBarChart rows={rows} metricCols={["acc"]} schema={null} />);
    expect(screen.getByText(/top 50 of 120/)).toBeInTheDocument();
    expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBeLessThanOrEqual(50);
  });

  it("ignores null (non-finite) metric values", () => {
    const rows = [row(1, { acc: null }), row(2, { acc: 0.5 })];
    render(<MetricBarChart rows={rows} metricCols={["acc"]} schema={null} />);
    expect(screen.queryByText(/top 50/)).toBeNull();
  });
});

describe("params come from row.params", () => {
  it("GroupedMetrics groups by a verbatim string param", () => {
    const rows = [
      row(1, { acc: 0.9 }, { model: "resnet50" }),
      row(2, { acc: 0.7 }, { model: "vit" }),
    ];
    render(<GroupedMetrics rows={rows} metricCols={["acc"]} paramCols={["model"]} schema={null} />);
    fireEvent.change(screen.getByDisplayValue("branch"), { target: { value: "model" } });
    expect(screen.getAllByText("resnet50").length).toBeGreaterThan(0);
    expect(screen.getAllByText("vit").length).toBeGreaterThan(0);
    expect(screen.queryByText("(none)")).toBeNull();
  });

  it("ParallelCoordinates draws a param axis from row.params", () => {
    const rows = [row(1, { acc: 0.9 }, { lr: 0.1 }), row(2, { acc: 0.7 }, { lr: 0.01 })];
    const { container } = render(
      <ParallelCoordinates rows={rows} metricCols={["acc"]} paramCols={["lr"]} schema={null} />,
    );
    const paths = [...container.querySelectorAll("[data-testid='row-line']")];
    // both rows reach the second (lr) axis: one move + one line command each
    for (const p of paths) expect((p.getAttribute("d") ?? "").includes("L")).toBe(true);
  });

  it("MetricScatter plots a numeric param from row.params", async () => {
    const originalMatchMedia = window.matchMedia;
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    resetInstances();
    enableCanvas();
    try {
      const rows = [row(1, { acc: 0.9 }, { lr: 0.1 }), row(2, { acc: 0.7 }, { lr: 0.01 })];
      render(<MetricScatter rows={rows} metricCols={["acc"]} paramCols={["lr"]} schema={null} />);
      await waitFor(() => expect(instances).toHaveLength(1));
      const [, ...groups] = instances[0].data as [null, ...[Float64Array, Float64Array][]];
      expect(groups.reduce((n, [xs]) => n + xs.length, 0)).toBe(2);
    } finally {
      window.matchMedia = originalMatchMedia;
      HTMLCanvasElement.prototype.getContext = originalGetContext;
    }
  });
});

describe("ParallelCoordinates brushing", () => {
  it("keeps the brushed selection after mouseup and can clear it", () => {
    const onBrush = vi.fn();
    const rows = [row(1, { loss: 0.5 }), row(2, { loss: 0.3 }), row(3, { loss: 0.7 })];
    const { container } = render(
      <ParallelCoordinates rows={rows} metricCols={["loss"]} paramCols={[]} schema={null} onBrush={onBrush} />,
    );
    const area = container.querySelector("[data-testid='brush-area']")!;
    fireEvent.mouseDown(area, { clientY: 20 });
    fireEvent.mouseMove(area, { clientY: 150 });
    fireEvent.mouseUp(area);
    expect(screen.getByText(/selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("clear"));
    expect(onBrush).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText(/selected/)).toBeNull();
  });
});
