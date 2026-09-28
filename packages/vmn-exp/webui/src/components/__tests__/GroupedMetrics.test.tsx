import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import GroupedMetrics from "../GroupedMetrics";
import type { ExperimentRow, MetricsSchema } from "../../types";

function row(
  idx: number,
  branch: string,
  metrics: Record<string, number>,
  user_meta?: Record<string, unknown> | null,
): ExperimentRow {
  return {
    idx,
    verstr: `1.0.0-dev.${String.fromCharCode(96 + idx)}`,
    code_verstr: `1.0.0-dev.${String.fromCharCode(96 + idx)}`,
    timestamp: null,
    note: null,
    branch,
    base_version: "1.0.0",
    user_meta: user_meta ?? null,
    metrics,
  };
}

const SCHEMA: MetricsSchema = {
  loss: { goal: "min" },
  acc: { goal: "max", primary: true },
};

describe("GroupedMetrics", () => {
  it("groups rows by branch and renders group labels", () => {
    const rows = [
      row(1, "main", { loss: 0.5, acc: 0.8 }),
      row(2, "main", { loss: 0.3, acc: 0.9 }),
      row(3, "feat", { loss: 0.7, acc: 0.7 }),
    ];

    render(
      <GroupedMetrics rows={rows} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />,
    );

    // Summary table should show both group names (chart also renders them as axis labels)
    expect(screen.getAllByText("main").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("feat").length).toBeGreaterThanOrEqual(1);

    // Verify table rows: header + 2 groups
    const tableRows = screen.getAllByRole("row");
    expect(tableRows.length).toBe(3); // 1 header + 2 data rows
  });

  it("computes correct mean for each group", () => {
    const rows = [
      row(1, "main", { loss: 0.4, acc: 0.8 }),
      row(2, "main", { loss: 0.6, acc: 0.6 }),
      row(3, "feat", { loss: 0.1, acc: 0.9 }),
    ];

    render(
      <GroupedMetrics rows={rows} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />,
    );

    // main group: mean loss = 0.5, mean acc = 0.7
    // feat group: mean loss = 0.1, mean acc = 0.9
    const cells = screen.getAllByRole("cell");
    const cellTexts = cells.map((c) => c.textContent);

    // Mean for main/loss = 0.5
    expect(cellTexts.some((t) => t?.includes("0.5"))).toBe(true);
    // Mean for main/acc = 0.7
    expect(cellTexts.some((t) => t?.includes("0.7"))).toBe(true);
  });

  it("computes correct std deviation for each group", () => {
    // main group: loss values [0.2, 0.8] => mean=0.5, std=0.3
    // main group: acc values [0.6, 1.0] => mean=0.8, std=0.2
    const rows = [
      row(1, "main", { loss: 0.2, acc: 0.6 }),
      row(2, "main", { loss: 0.8, acc: 1.0 }),
    ];

    render(
      <GroupedMetrics rows={rows} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />,
    );

    const cells = screen.getAllByRole("cell");
    const cellTexts = cells.map((c) => c.textContent);

    // Should contain the std value 0.3 somewhere in a "mean +/- std" display
    expect(cellTexts.some((t) => t?.includes("0.3"))).toBe(true);
    expect(cellTexts.some((t) => t?.includes("0.2"))).toBe(true);
  });

  it("handles single-row groups (std = 0)", () => {
    const rows = [
      row(1, "solo", { loss: 0.42, acc: 0.88 }),
    ];

    render(
      <GroupedMetrics rows={rows} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />,
    );

    expect(screen.getAllByText("solo").length).toBeGreaterThanOrEqual(1);

    const cells = screen.getAllByRole("cell");
    const cellTexts = cells.map((c) => c.textContent);
    // std=0 means the display should show 0 for deviation
    expect(cellTexts.some((t) => t?.includes("0.42"))).toBe(true);
  });

  it("handles empty data gracefully", () => {
    const { container } = render(
      <GroupedMetrics rows={[]} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} />,
    );

    // Should render without crashing; no groups to show
    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain("No groups");
  });
});
