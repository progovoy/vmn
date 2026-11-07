import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricBarChart from "../MetricBarChart";
import type { ExperimentRow, MetricsSchema } from "../../types";

const ROWS: ExperimentRow[] = [
  { idx: 1, verstr: "1.0.0-dev.a", code_verstr: "1.0.0-dev.a", timestamp: null, note: "run 1", branch: "main", base_version: "1.0.0", metrics: { loss: 0.5, acc: 0.8 } },
  { idx: 2, verstr: "1.0.0-dev.b", code_verstr: "1.0.0-dev.b", timestamp: null, note: "run 2", branch: "main", base_version: "1.0.0", metrics: { loss: 0.3, acc: 0.9 } },
  { idx: 3, verstr: "1.0.0-dev.c", code_verstr: "1.0.0-dev.c", timestamp: null, note: "run 3", branch: "main", base_version: "1.0.0", metrics: { loss: 0.7, acc: 0.7 } },
];

const SCHEMA: MetricsSchema = {
  loss: { goal: "min" },
  acc: { goal: "max", primary: true },
};

describe("MetricBarChart", () => {
  it("renders a metric selector dropdown", () => {
    render(<MetricBarChart rows={ROWS} metricCols={["loss", "acc"]} schema={SCHEMA} />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("renders a chart container", () => {
    const { container } = render(
      <MetricBarChart rows={ROWS} metricCols={["loss", "acc"]} schema={SCHEMA} />
    );
    expect(container.querySelector("[data-testid='bar-chart']")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-testid='bar']")).toHaveLength(3);
  });

  it("shows metric options in the dropdown", () => {
    render(<MetricBarChart rows={ROWS} metricCols={["loss", "acc"]} schema={SCHEMA} />);
    const options = screen.getByRole("combobox").querySelectorAll("option");
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toBe("loss");
    expect(options[1].textContent).toBe("acc");
  });

  it("handles empty rows gracefully", () => {
    const { container } = render(
      <MetricBarChart rows={[]} metricCols={["loss"]} schema={SCHEMA} />
    );
    expect(container.querySelector("[data-testid='bar-chart']")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-testid='bar']")).toHaveLength(0);
  });

  it("charts the first metric once the metrics arrive after it mounted", () => {
    const { container, rerender } = render(<MetricBarChart rows={ROWS} metricCols={[]} schema={SCHEMA} />);
    rerender(<MetricBarChart rows={ROWS} metricCols={["loss", "acc"]} schema={SCHEMA} />);
    expect(container.querySelectorAll("[data-testid='bar']")).toHaveLength(3);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("loss");
  });

  it("orders a goal-less metric's bars ascending and calls none the top (plan 32 F4)", () => {
    const { container } = render(<MetricBarChart rows={ROWS} metricCols={["loss"]} schema={{}} />);
    const labels = [...container.querySelectorAll("[data-testid='bar']")].map((b) => b.textContent);
    expect(labels.map((t) => t?.slice(0, 2))).toEqual(["@2", "@1", "@3"]);
  });

  it("labels a run the server has not indexed (idx 0) by its verstr", () => {
    const { container } = render(<MetricBarChart rows={[{ ...ROWS[0], idx: 0 }]} metricCols={["loss"]} schema={SCHEMA} />);
    expect(container.querySelector("[data-testid='bar']")!.textContent).toContain("1.0.0-dev.a");
  });

  it("captions a capped goal-less chart by order, not as the top runs", () => {
    const many = Array.from({ length: 60 }, (_, i) => ({ ...ROWS[0], idx: i + 1, verstr: `v${i}`, metrics: { size: i } }));
    render(<MetricBarChart rows={many} metricCols={["size"]} schema={{}} />);
    expect(screen.getByText(/of 60 runs/).textContent).toBe("showing the first 50 of 60 runs by size, ascending (no goal)");
  });
});
