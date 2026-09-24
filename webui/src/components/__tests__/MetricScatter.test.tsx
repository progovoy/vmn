import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import MetricScatter from "../MetricScatter";
import type { ExperimentRow, MetricsSchema } from "../../types";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
  // Distinct theme colours, so the two point groups can be told apart.
  document.documentElement.style.setProperty("--accent", "#0000ff");
  document.documentElement.style.setProperty("--good", "#00ff00");
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

type Pts = [Float64Array, Float64Array];
/** The plotted groups of the (only) chart: [rest, best]. */
async function plotted(): Promise<{ rest: Pts; best: Pts; fills: unknown[] }> {
  await waitFor(() => expect(instances.length).toBeGreaterThan(0));
  const u = instances[instances.length - 1];
  const [, rest, best] = u.data as [null, Pts, Pts];
  const series = u.opts.series as { points?: { fill?: unknown } }[];
  return { rest, best, fills: series.slice(1).map((s) => s.points?.fill) };
}
const count = (p: Pts) => p[0].length;

const ROWS: ExperimentRow[] = [
  { idx: 1, verstr: "1.0.0-dev.a", code_verstr: "1.0.0-dev.a", timestamp: null, note: "run 1", branch: "main", base_version: "1.0.0", user_meta: { lr: 0.01 }, metrics: { loss: 0.5, acc: 0.8 } },
  { idx: 2, verstr: "1.0.0-dev.b", code_verstr: "1.0.0-dev.b", timestamp: null, note: "run 2", branch: "main", base_version: "1.0.0", user_meta: { lr: 0.001 }, metrics: { loss: 0.3, acc: 0.9 } },
  { idx: 3, verstr: "1.0.0-dev.c", code_verstr: "1.0.0-dev.c", timestamp: null, note: "run 3", branch: "main", base_version: "1.0.0", user_meta: { lr: 0.1 }, metrics: { loss: 0.7, acc: 0.7 } },
];

const SCHEMA: MetricsSchema = {
  loss: { goal: "min" },
  acc: { goal: "max", primary: true },
};

describe("MetricScatter", () => {
  it("renders a ScatterChart with correct data points", async () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr"]} schema={SCHEMA} />
    );
    expect(container.querySelector("[data-testid='scatter-chart']")).toBeInTheDocument();
    // All 3 rows have numeric values for both default axes, so 3 points
    const { rest, best } = await plotted();
    expect(count(rest) + count(best)).toBe(3);
  });

  it("skips rows with missing X or Y values", async () => {
    const rowsWithGap: ExperimentRow[] = [
      ...ROWS,
      { idx: 4, verstr: "1.0.0-dev.d", code_verstr: "1.0.0-dev.d", timestamp: null, note: "run 4", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.4 } },
    ];
    render(
      <MetricScatter rows={rowsWithGap} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />
    );
    // Row 4 has no "acc" metric, so only 3 points should be plotted
    const { rest, best } = await plotted();
    expect(count(rest) + count(best)).toBe(3);
  });

  it("renders X and Y axis dropdowns that change the chart", async () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr"]} schema={SCHEMA} />
    );
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBe(2);

    // Change Y axis to "loss"
    fireEvent.change(selects[1], { target: { value: "loss" } });

    // Chart should still render, now plotting loss on Y
    expect(container.querySelector("[data-testid='scatter-chart']")).toBeInTheDocument();
    const { rest, best } = await plotted();
    expect([...rest[1], ...best[1]].sort()).toEqual([0.3, 0.5, 0.7]);
  });

  it("highlights the best point based on Y-axis goal", async () => {
    render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />
    );
    // Default Y axis = "acc" (second metric). Goal is "max", best = 0.9.
    // Two point groups: rest (accent) and best (good).
    const { rest, best, fills } = await plotted();
    expect(count(rest)).toBe(2); // two non-best rows
    expect(count(best)).toBe(1); // one best row
    expect([...best[1]]).toEqual([0.9]);
    expect(fills).toEqual(["#0000ff", "#00ff00"]);
  });

  it("handles empty data gracefully", () => {
    const { container } = render(
      <MetricScatter rows={[]} metricCols={["loss"]} paramCols={[]} schema={SCHEMA} />
    );
    expect(container.querySelector("[data-testid='scatter-chart']")).toBeInTheDocument();
  });
});
