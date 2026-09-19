import { describe, it, expect, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import MetricScatter from "../MetricScatter";
import type { ExperimentRow, MetricsSchema } from "../../types";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

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
  it("renders a ScatterChart with correct data points", () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr"]} schema={SCHEMA} />
    );
    expect(container.querySelector(".recharts-wrapper")).toBeInTheDocument();
    // All 3 rows have numeric values for both default axes, so 3 scatter symbols
    const symbols = container.querySelectorAll(".recharts-symbols");
    expect(symbols.length).toBe(3);
  });

  it("skips rows with missing X or Y values", () => {
    const rowsWithGap: ExperimentRow[] = [
      ...ROWS,
      { idx: 4, verstr: "1.0.0-dev.d", code_verstr: "1.0.0-dev.d", timestamp: null, note: "run 4", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.4 } },
    ];
    const { container } = render(
      <MetricScatter rows={rowsWithGap} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />
    );
    // Row 4 has no "acc" metric, so only 3 dots should render
    const symbols = container.querySelectorAll(".recharts-symbols");
    expect(symbols.length).toBe(3);
  });

  it("renders X and Y axis dropdowns that change the chart", () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={["lr"]} schema={SCHEMA} />
    );
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBe(2);

    // Change Y axis to "loss"
    fireEvent.change(selects[1], { target: { value: "loss" } });

    // Chart should still render
    expect(container.querySelector(".recharts-wrapper")).toBeInTheDocument();
  });

  it("highlights the best point based on Y-axis goal", () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />
    );
    // Default Y axis = "acc" (second metric). Goal is "max", best = 0.9.
    // Recharts renders two Scatter layers: rest (accent) and best (good).
    const scatterLayers = container.querySelectorAll(".recharts-scatter");
    expect(scatterLayers.length).toBe(2);
    // First layer: normal dots with accent fill
    const normalPaths = scatterLayers[0].querySelectorAll("path");
    expect(normalPaths.length).toBe(2); // two non-best rows
    normalPaths.forEach((p) => expect(p.getAttribute("fill")).toBe("var(--accent)"));
    // Second layer: best dot with good fill
    const bestPaths = scatterLayers[1].querySelectorAll("path");
    expect(bestPaths.length).toBe(1); // one best row
    bestPaths.forEach((p) => expect(p.getAttribute("fill")).toBe("var(--good)"));
  });

  it("handles empty data gracefully", () => {
    const { container } = render(
      <MetricScatter rows={[]} metricCols={["loss"]} paramCols={[]} schema={SCHEMA} />
    );
    expect(container.querySelector(".recharts-wrapper")).toBeInTheDocument();
  });
});
