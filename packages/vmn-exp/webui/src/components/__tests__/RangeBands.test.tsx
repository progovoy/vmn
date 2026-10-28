import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import { rangeBandsHook } from "../../util/chartMarkers";
import type { SeriesPoint } from "../../types";

const pts = (n: number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: 1 / (i + 1), ts: `2026-01-01T00:00:0${i}Z` }));

const RANGES = [{ name: "swa", start_step: 2, end_step: 6 }];

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

type Hooks = { drawClear?: ((u: unknown) => void)[] };
const bandHooks = (i: number) => ((instances[i].opts.hooks as Hooks | undefined)?.drawClear ?? []);

describe("logged ranges on the Run page charts", () => {
  it("shades the ranges on every step chart", async () => {
    renderWithClient(<TrainingCurves series={{ loss: pts(10), acc: pts(10) }} ranges={RANGES} />);
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(bandHooks(0)).toHaveLength(1);
    expect(bandHooks(1)).toHaveLength(1);
    const charts = screen.getAllByTestId("metric-chart");
    expect(charts.map((c) => c.getAttribute("data-ranges"))).toEqual(["1", "1"]);
  });

  it("names the ranges under the toolbar", async () => {
    renderWithClient(<TrainingCurves series={{ loss: pts(10) }} ranges={RANGES} />);
    expect(await screen.findByText(/swa 2–6/)).toBeInTheDocument();
  });

  it("draws no band without ranges or off step axes", async () => {
    renderWithClient(<TrainingCurves series={{ loss: pts(10) }} ranges={RANGES} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: /relative/i }));
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(bandHooks(1)).toHaveLength(0);
  });
});

describe("rangeBandsHook", () => {
  const ctx = () => ({ save: vi.fn(), restore: vi.fn(), fillRect: vi.fn(), fillStyle: "" });

  it("fills each range between its step positions, clipped to the plot", () => {
    const c = ctx();
    const u = {
      ctx: c, bbox: { left: 10, top: 5, width: 100, height: 50 },
      valToPos: vi.fn((v: number) => 10 + v * 10), scales: { x: { min: 0, max: 10 } },
    };
    rangeBandsHook([{ name: "a", start_step: 2, end_step: 4 }, { name: "b", start_step: 8, end_step: 30 }], "#0f0")(u as never);
    expect(c.fillRect).toHaveBeenNthCalledWith(1, 30, 5, 20, 50);
    expect(c.fillRect).toHaveBeenNthCalledWith(2, 90, 5, 20, 50);
  });

  it("skips a range outside the visible x range", () => {
    const c = ctx();
    const u = { ctx: c, bbox: {}, valToPos: vi.fn(), scales: { x: { min: 10, max: 20 } } };
    rangeBandsHook([{ name: "a", start_step: 2, end_step: 4 }], "#0f0")(u as never);
    expect(c.fillRect).not.toHaveBeenCalled();
  });
});
