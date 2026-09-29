import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import FakeUPlot, { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import { XMetricSelect } from "../ChartControls";
import type { SeriesPoint } from "../../types";

const pts = (n: number, f: (i: number) => number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: f(i), ts: null }));

const SERIES = {
  loss: pts(6, (i) => 1 / (i + 1)),
  val_loss: pts(6, (i) => 2 / (i + 1)),
  epoch: pts(6, (i) => Math.floor(i / 2)),
};

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

/** The xs the newest plot inside *metric*'s chart was last given. */
function plottedXs(metric: string): number[] {
  const cell = screen.getAllByTestId("metric-chart").find((el) => el.getAttribute("data-metric") === metric)!;
  const plot = [...instances].reverse().find((u: FakeUPlot) => cell.contains(u.el))!;
  const calls = plot.setData.mock.calls;
  const data = (calls.length ? calls[calls.length - 1][0] : plot.data) as [null, [Float64Array, Float64Array]];
  return Array.from(data[1][0]);
}

describe("XMetricSelect", () => {
  it("offers declared, none and every metric, and is off outside step mode", () => {
    const { rerender } = render(
      <XMetricSelect value="auto" onChange={() => {}} metrics={["epoch", "lr"]} enabled />,
    );
    const select = screen.getByRole("combobox", { name: /x axis metric/i });
    const values = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(values).toEqual(["auto", "none", "epoch", "lr"]);
    rerender(<XMetricSelect value="auto" onChange={() => {}} metrics={["epoch"]} enabled={false} />);
    expect(screen.getByRole("combobox", { name: /x axis metric/i })).toBeDisabled();
  });
});

describe("TrainingCurves x metric", () => {
  it("plots a metric against its declared step metric by default", async () => {
    const joined = { val_loss: [0, 2, 4].map((s, i) => ({ step: s, ts: null, value: 1, x: i * 10 })) };
    const fetchJoined = vi.fn().mockResolvedValue(joined);
    renderWithClient(<TrainingCurves series={SERIES} stepMetrics={{ val_loss: "epoch" }} fetchJoined={fetchJoined} />,
    );
    await waitFor(() => expect(fetchJoined).toHaveBeenCalledWith({ val_loss: "epoch" }));
    await waitFor(() => expect(plottedXs("val_loss")).toEqual([0, 10, 20]));
    expect(plottedXs("loss")).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("picking a metric joins every other chart on it", async () => {
    const fetchJoined = vi.fn().mockResolvedValue({});
    renderWithClient(<TrainingCurves series={SERIES} fetchJoined={fetchJoined} />);
    expect(fetchJoined).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: /x axis metric/i }), { target: { value: "epoch" } });
    await waitFor(() =>
      expect(fetchJoined).toHaveBeenCalledWith({ loss: "epoch", val_loss: "epoch" }));
  });

  it("none keeps declared metrics on the step axis", async () => {
    const fetchJoined = vi.fn().mockResolvedValue({});
    renderWithClient(<TrainingCurves series={SERIES} stepMetrics={{ val_loss: "epoch" }} fetchJoined={fetchJoined} />,
    );
    await waitFor(() => expect(fetchJoined).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("combobox", { name: /x axis metric/i }), { target: { value: "none" } });
    await waitFor(() => expect(plottedXs("val_loss")).toEqual([0, 1, 2, 3, 4, 5]));
    expect(fetchJoined).toHaveBeenCalledTimes(1);
  });

  it("shows a failed join and keeps the chart on the step axis", async () => {
    const fetchJoined = vi.fn().mockRejectedValue(new Error("join exploded"));
    renderWithClient(<TrainingCurves series={SERIES} stepMetrics={{ val_loss: "epoch" }} fetchJoined={fetchJoined} />,
    );
    expect(await screen.findByText(/join exploded/)).toBeInTheDocument();
    expect(plottedXs("val_loss")).toEqual([0, 1, 2, 3, 4, 5]);
  });
});
