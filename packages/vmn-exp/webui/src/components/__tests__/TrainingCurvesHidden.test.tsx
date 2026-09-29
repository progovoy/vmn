import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (n: number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: i, ts: null }));

const SERIES = { loss: pts(5), grad_norm: pts(5), lr: pts(5) };

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const chartTitles = () =>
  screen.getAllByTestId("metric-chart").map((el) => el.getAttribute("data-metric"));

describe("TrainingCurves hidden metrics", () => {
  it("keeps hidden metrics in a collapsed section of their own", () => {
    renderWithClient(<TrainingCurves series={SERIES} hiddenMetrics={["grad_norm", "lr"]} />);
    expect(chartTitles()).toEqual(["loss"]);
    fireEvent.click(screen.getByText(/show hidden metrics \(2\)/));
    expect(chartTitles()).toEqual(["loss", "grad_norm", "lr"]);
  });

  it("draws every metric in the main grid without hidden ones", () => {
    renderWithClient(<TrainingCurves series={SERIES} />);
    expect(chartTitles()).toEqual(["loss", "grad_norm", "lr"]);
    expect(screen.queryByText(/hidden metrics/)).toBeNull();
  });
});
