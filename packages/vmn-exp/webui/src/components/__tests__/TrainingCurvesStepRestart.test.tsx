import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (steps: number[]): SeriesPoint[] => steps.map((step) => ({ step, value: step, ts: null }));

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("TrainingCurves step restarts", () => {
  it("notes on a metric's chart where its steps went back", () => {
    renderWithClient(
      <TrainingCurves
        series={{ best: pts([0, 1, 2, 0]), loss: pts([0, 1]) }}
        stepRestarts={{ best: { write: 4, from: 2, to: 0 } }}
      />,
    );
    expect(screen.getByTestId("chart-restart-best").textContent).toBe("steps went back from 2 to 0 at write 4");
    expect(screen.queryByTestId("chart-restart-loss")).toBeNull();
  });
});
