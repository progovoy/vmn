import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricBarChart from "../MetricBarChart";
import type { ExperimentRow, MetricsSchema } from "../../types";

const ROWS: ExperimentRow[] = [
  { idx: 1, verstr: "1.0.0-dev.a", code_verstr: "1.0.0-dev.a", timestamp: null, note: "run 1", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.5, acc: 0.8 } },
  { idx: 2, verstr: "1.0.0-dev.b", code_verstr: "1.0.0-dev.b", timestamp: null, note: "run 2", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.3, acc: 0.9 } },
  { idx: 3, verstr: "1.0.0-dev.c", code_verstr: "1.0.0-dev.c", timestamp: null, note: "run 3", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.7, acc: 0.7 } },
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
});
