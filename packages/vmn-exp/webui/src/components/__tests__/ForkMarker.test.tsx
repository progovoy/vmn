import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import { stepMarkerHook } from "../../util/chartMarkers";
import type { SeriesPoint } from "../../types";

const pts = (n: number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: 1 / (i + 1), ts: null }));

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

type Hooks = { draw?: ((u: unknown) => void)[] };
const drawHooks = (i: number) => ((instances[i].opts.hooks as Hooks | undefined)?.draw ?? []);

describe("fork point on the Run page charts", () => {
  it("marks the fork step on every step chart", async () => {
    renderWithClient(<TrainingCurves series={{ loss: pts(10), acc: pts(10) }} markStep={4} />);
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(drawHooks(0)).toHaveLength(1);
    const charts = screen.getAllByTestId("metric-chart");
    expect(charts.map((c) => c.getAttribute("data-mark-step"))).toEqual(["4", "4"]);
  });

  it("draws no marker without a fork step", async () => {
    renderWithClient(<TrainingCurves series={{ loss: pts(10) }} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    expect(drawHooks(0)).toHaveLength(0);
    expect(screen.getByTestId("metric-chart").getAttribute("data-mark-step")).toBeNull();
  });

  it("drops the marker off step axes", async () => {
    const series = { loss: pts(10).map((p, i) => ({ ...p, ts: `2026-01-01T00:00:0${i}Z` })) };
    renderWithClient(<TrainingCurves series={series} markStep={4} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: /relative/i }));
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(drawHooks(1)).toHaveLength(0);
  });
});

describe("stepMarkerHook", () => {
  it("strokes a vertical line at the step's x position", () => {
    const ctx = {
      save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
      stroke: vi.fn(), setLineDash: vi.fn(), strokeStyle: "", lineWidth: 0,
    };
    const u = {
      ctx, bbox: { left: 10, top: 5, width: 100, height: 50 },
      valToPos: vi.fn((v: number) => v * 2), scales: { x: { min: 0, max: 50 } },
    };
    stepMarkerHook(7, "#f00")(u as never);
    expect(u.valToPos).toHaveBeenCalledWith(7, "x", true);
    expect(ctx.moveTo).toHaveBeenCalledWith(14, 5);
    expect(ctx.lineTo).toHaveBeenCalledWith(14, 55);
    expect(ctx.stroke).toHaveBeenCalled();
  });

  it("skips a step outside the visible x range", () => {
    const ctx = { save: vi.fn(), restore: vi.fn(), stroke: vi.fn() };
    const u = { ctx, bbox: {}, valToPos: vi.fn(), scales: { x: { min: 10, max: 20 } } };
    stepMarkerHook(7, "#f00")(u as never);
    expect(ctx.stroke).not.toHaveBeenCalled();
  });
});
