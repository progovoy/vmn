/** Plan 20 E5: the leaderboard's Trend cards read as one family — one
 *  accent series colour on every card, x tick labels on, "best" only for a
 *  metric with a direction (D1). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import ParamPlots from "../ParamPlots";
import type { ExperimentRow } from "../../types";

const row = (i: number, metrics: Record<string, number>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", metrics,
});

type Opts = { series: { stroke?: string }[]; axes: { show?: boolean }[] };
const optsOf = (i: number) => instances[i].opts as unknown as Opts;

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
  document.documentElement.style.setProperty("--accent", "#3b82f6");
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
  document.documentElement.style.removeProperty("--accent");
});

const rows = [
  row(1, { loss: 0.5, acc: 0.1, grad_norm: 3 }),
  row(2, { loss: 0.4, acc: 0.3, grad_norm: 2 }),
];
const cols = ["loss", "acc", "grad_norm"];

describe("ParamPlots trend cards (E5)", () => {
  it("draws every card's series in the one accent colour", async () => {
    render(<ParamPlots rows={rows} metricCols={cols} schema={null} />);
    await waitFor(() => expect(instances).toHaveLength(3));
    const strokes = instances.map((_, i) => optsOf(i).series[1].stroke);
    expect(new Set(strokes).size).toBe(1);
    expect(strokes[0]).toBe("#3b82f6");
  });

  it("shows the x axis tick labels", async () => {
    render(<ParamPlots rows={rows} metricCols={["loss"]} schema={null} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    expect(optsOf(0).axes[0].show).not.toBe(false);
  });

  it("marks best only on a metric with a direction", () => {
    render(<ParamPlots rows={rows} metricCols={cols} schema={null} />);
    // loss (MIN_LIKE) and acc (MAX_LIKE) have one; grad_norm has none (D1).
    const best = screen.getAllByText(/^best /);
    expect(best.map((b) => b.textContent)).toEqual(["best 0.4", "best 0.3"]);
    for (const b of best) expect(b).toHaveStyle({ color: "var(--good)" });
  });
});
