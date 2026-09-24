import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import type { SeriesPoint } from "../../types";

const pts = (n: number, f: (i: number) => number): SeriesPoint[] =>
  Array.from({ length: n }, (_, i) => ({ step: i, value: f(i), ts: null }));

const SERIES = {
  loss: pts(10, (i) => 1 / (i + 1)),
  val_loss: pts(5, (i) => 2 / (i + 1)),
  acc: pts(10, (i) => i / 10),
  sys_rss_mb: pts(3, (i) => 1000 + i),
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

const chartTitles = () =>
  screen.getAllByTestId("metric-chart").map((el) => el.getAttribute("data-metric"));

describe("TrainingCurves small multiples", () => {
  it("draws one chart per training metric, each on its own axis", async () => {
    render(<TrainingCurves series={SERIES} />);
    expect(chartTitles()).toEqual(["loss", "val_loss", "acc"]);
    await waitFor(() => expect(instances).toHaveLength(3));
  });

  it("filters the charts with the metric search box", () => {
    render(<TrainingCurves series={SERIES} />);
    fireEvent.change(screen.getByPlaceholderText(/filter metrics/i), { target: { value: "LOSS" } });
    expect(chartTitles()).toEqual(["loss", "val_loss"]);
  });

  it("says when the search matches nothing", () => {
    render(<TrainingCurves series={SERIES} />);
    fireEvent.change(screen.getByPlaceholderText(/filter metrics/i), { target: { value: "zzz" } });
    expect(screen.queryAllByTestId("metric-chart")).toHaveLength(0);
    expect(screen.getByText(/no metric matches/i)).toBeInTheDocument();
  });

  it("toggles a log y axis", async () => {
    render(<TrainingCurves series={{ loss: SERIES.loss }} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    const btn = screen.getByRole("button", { name: /log/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(instances).toHaveLength(2));
    const scales = instances[1].opts.scales as { y: { distr: number } };
    expect(scales.y.distr).toBe(3);
  });

  it("adds a faded raw curve under the smoothed one", async () => {
    render(<TrainingCurves series={{ loss: SERIES.loss }} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.5" } });
    await waitFor(() => {
      const last = instances[instances.length - 1];
      expect((last.opts.series as unknown[]).length).toBe(3);
    });
  });

  it("keeps sys_* metrics in their own section until asked for", () => {
    render(<TrainingCurves series={SERIES} />);
    expect(chartTitles()).not.toContain("sys_rss_mb");
    fireEvent.click(screen.getByText(/show system metrics \(1\)/));
    expect(chartTitles()).toContain("sys_rss_mb");
  });

  it("renders nothing without plottable series", () => {
    const { container } = render(<TrainingCurves series={{ loss: pts(1, () => 1) }} />);
    expect(container.firstChild).toBeNull();
  });
});
