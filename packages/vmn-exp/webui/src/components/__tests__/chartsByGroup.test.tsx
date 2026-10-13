/** On a grouped board the Charts tab colours every run by its group
 *  (plan 22 G7): bars, scatter points and parallel lines. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import MetricBarChart from "../MetricBarChart";
import MetricScatter from "../MetricScatter";
import ParallelCoordinates from "../ParallelCoordinates";
import type { ExperimentRow, MetricsSchema } from "../../types";
import type { ChartGroups } from "../../util/chartGroups";

const row = (c: string, loss: number, acc: number): ExperimentRow => ({
  idx: c.charCodeAt(0) - 96, verstr: `v.${c}`, code_verstr: `v.${c}`, timestamp: null, note: null,
  branch: "main", base_version: "1.0.0", params: {}, metrics: { loss, acc },
});
const ROWS = [row("a", 0.5, 0.8), row("b", 0.3, 0.9), row("c", 0.7, 0.7)];
const SCHEMA: MetricsSchema = { loss: { goal: "min" }, acc: { goal: "max", primary: true } };
const GROUPS: ChartGroups = {
  colorOf: new Map([["v.a", "var(--minor)"], ["v.b", "var(--hotfix)"], ["v.c", "var(--minor)"]]),
  legend: [
    { key: "s", label: "sweep", color: "var(--minor)", count: 2 },
    { key: "t", label: "t", color: "var(--hotfix)", count: 1 },
  ],
};

beforeEach(() => {
  resetInstances();
  enableCanvas();
  document.documentElement.style.setProperty("--minor", "#0000ff");
  document.documentElement.style.setProperty("--hotfix", "#ff0000");
});

describe("charts coloured by group", () => {
  it("fills each bar with its run's group colour", () => {
    render(<MetricBarChart rows={ROWS} metricCols={["loss"]} schema={SCHEMA} groups={GROUPS} />);
    const fills = screen.getAllByTestId("bar-fill").map((el) => (el as HTMLElement).style.background);
    // Best-first by loss: b, a, c.
    expect(fills).toEqual(["var(--hotfix)", "var(--minor)", "var(--minor)"]);
  });

  it("plots one point series per group, in the legend's colours", async () => {
    render(<MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} groups={GROUPS} />);
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    const u = instances[instances.length - 1];
    const series = (u.opts.series as { points?: { fill?: unknown } }[]).slice(1);
    expect(series.map((s) => s.points?.fill)).toEqual(["#0000ff", "#ff0000"]);
    const [, sweep, t] = u.data as [null, Float64Array[], Float64Array[]];
    expect([...sweep[0]].sort()).toEqual([0.5, 0.7]);
    expect([...t[0]]).toEqual([0.3]);
  });

  it("colours parallel lines by group by default, and still by a metric on request", () => {
    const { container } = render(
      <ParallelCoordinates rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={SCHEMA} groups={GROUPS} />,
    );
    const select = screen.getByRole("combobox", { name: "color by" }) as HTMLSelectElement;
    expect(select.value).toBe("group:");
    expect(select.selectedOptions[0].textContent).toBe("group");
    const strokes = () => [...container.querySelectorAll('[data-testid="row-line"]')].map((p) => p.getAttribute("stroke"));
    expect(strokes()).toEqual(["var(--minor)", "var(--hotfix)", "var(--minor)"]);
    fireEvent.change(select, { target: { value: "acc" } });
    expect(strokes().some((s) => s?.startsWith("var("))).toBe(false);
  });
});
