import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (steps: number[], v: number): SeriesPoint[] =>
  steps.map((step) => ({ step, value: v, ts: null }));
const range = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

const COARSE = { loss: pts([0, 25, 50, 75, 99], 1) };

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

const lastYs = (i: number) => {
  const calls = instances[i].setData.mock.calls;
  const data = calls[calls.length - 1][0] as [null, [Float64Array, Float64Array]];
  return Array.from(data[1][1]);
};

describe("TrainingCurves zoom", () => {
  it("refetches the zoomed step range and splices it over the coarse series", async () => {
    const fetchRange = vi.fn().mockResolvedValue(pts(range(20, 30), 9));
    renderWithClient(<TrainingCurves series={COARSE} fetchRange={fetchRange} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    act(() => instances[0].zoomX(20, 30));
    await waitFor(() => expect(fetchRange).toHaveBeenCalledWith("loss", 20, 30));
    expect(fetchRange).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(lastYs(0).filter((v) => v === 9)).toHaveLength(11));
    // The coarse points outside the range stay as the background.
    expect(lastYs(0).filter((v) => v === 1)).toHaveLength(4);
    // New data must not undo the zoom.
    expect(instances[0].setScale).toHaveBeenCalledWith("x", { min: 20, max: 30 });
  });

  it("does not fetch when the x axis is reset to the whole series", async () => {
    const fetchRange = vi.fn().mockResolvedValue([]);
    renderWithClient(<TrainingCurves series={COARSE} fetchRange={fetchRange} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    act(() => instances[0].zoomX(0, 99));
    await new Promise((r) => setTimeout(r, 400));
    expect(fetchRange).not.toHaveBeenCalled();
  });
});
