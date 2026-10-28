import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const pts = (values: number[]): SeriesPoint[] =>
  values.map((value, step) => ({ step, value, ts: null }));

const SERIES = { loss: pts([3, 2, 1]), "health.mem": pts([0.2, 0.9, 0.5]), lr: pts([1, 2]) };

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const curveTitles = () =>
  screen.getAllByTestId("metric-chart").map((el) => el.getAttribute("data-metric"));

describe("TrainingCurves chart hints (plan 28 N8)", () => {
  it("draws a bars metric as bars sorted by value with its max and share", () => {
    renderWithClient(<TrainingCurves series={SERIES} metricCharts={{ "health.mem": "bars" }} />);
    expect(curveTitles()).toEqual(["loss", "lr"]);
    const bars = screen.getByTestId("metric-bars");
    expect(bars.getAttribute("data-metric")).toBe("health.mem");
    const labels = within(bars).getAllByTestId("bar-step").map((el) => el.textContent);
    expect(labels).toEqual(["1", "2", "0"]);
    expect(within(bars).getByText(/max 0\.9/)).toBeTruthy();
    fireEvent.change(within(bars).getByLabelText("threshold"), { target: { value: "0.4" } });
    expect(within(bars).getByText(/2 of 3 \(67%\) > 0\.4/)).toBeTruthy();
  });

  it("lists a table metric as step -> value", () => {
    renderWithClient(<TrainingCurves series={SERIES} metricCharts={{ lr: "table" }} />);
    expect(curveTitles()).toEqual(["loss", "health.mem"]);
    const table = screen.getByTestId("metric-table");
    const cells = within(table).getAllByRole("row").slice(1).map((r) =>
      within(r).getAllByRole("cell").map((c) => c.textContent));
    expect(cells).toEqual([["0", "1"], ["1", "2"]]);
  });

  it("keeps a hinted hidden metric in the hidden section", () => {
    renderWithClient(
      <TrainingCurves series={SERIES} hiddenMetrics={["lr"]} metricCharts={{ lr: "table" }} />,
    );
    expect(screen.queryByTestId("metric-table")).toBeNull();
    fireEvent.click(screen.getByText(/show hidden metrics \(1\)/));
    expect(screen.getByTestId("metric-table").getAttribute("data-metric")).toBe("lr");
  });
});
