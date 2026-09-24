import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import CurveChart from "../CurveChart";
import type { CurveSeries } from "../../util/curveOptions";

const flat = (key: string, v: number, extra: Partial<CurveSeries> = {}): CurveSeries => ({
  key, label: key, color: "#123456",
  xs: Float64Array.from([0, 1, 2]), ys: Float64Array.from([v, v, v]), ...extra,
});

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

describe("CurveChart", () => {
  it("builds one faceted uPlot with a series per curve", async () => {
    render(<CurveChart series={[flat("a", 1), flat("b", 2)]} xMode="step" />);
    await waitFor(() => expect(instances).toHaveLength(1));
    expect(instances[0].opts.mode).toBe(2);
    expect((instances[0].opts.series as unknown[]).length).toBe(3);
  });

  it("updates data in place when only the values change", async () => {
    const { rerender } = render(<CurveChart series={[flat("a", 1)]} xMode="step" />);
    await waitFor(() => expect(instances).toHaveLength(1));
    rerender(<CurveChart series={[flat("a", 5)]} xMode="step" />);
    expect(instances).toHaveLength(1);
    expect(instances[0].setData).toHaveBeenCalled();
  });

  it("rebuilds when the axis kind changes", async () => {
    const { rerender } = render(<CurveChart series={[flat("a", 1)]} xMode="step" />);
    await waitFor(() => expect(instances).toHaveLength(1));
    rerender(<CurveChart series={[flat("a", 1)]} xMode="step" logY />);
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(instances[0].destroyed).toBe(true);
  });

  it("shows a tooltip sorted by value and capped to the runs nearest the cursor", async () => {
    const series = [flat("a", 1), flat("b", 5), flat("c", 3), flat("d", 10)];
    render(<CurveChart series={series} xMode="step" tooltipLimit={2} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    act(() => instances[0].moveCursor(1, 4));
    const tip = screen.getByTestId("curve-tooltip");
    const labels = [...tip.querySelectorAll("[data-key]")].map((el) => el.getAttribute("data-key"));
    expect(labels).toEqual(["b", "c"]);
    act(() => instances[0].moveCursor(-10, -10));
    expect(screen.queryByTestId("curve-tooltip")).toBeNull();
  });

  it("leaves hidden and faded (raw) series out of the tooltip", async () => {
    const series = [flat("a", 1), flat("a_raw", 2, { faded: true }), flat("b", 3)];
    render(<CurveChart series={series} xMode="step" hidden={new Set(["b"])} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    act(() => instances[0].moveCursor(1, 1));
    const keys = [...screen.getByTestId("curve-tooltip").querySelectorAll("[data-key]")]
      .map((el) => el.getAttribute("data-key"));
    expect(keys).toEqual(["a"]);
  });

  it("hides and focuses series through uPlot", async () => {
    const series = [flat("a", 1), flat("b", 2)];
    const { rerender } = render(<CurveChart series={series} xMode="step" hidden={new Set(["b"])} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    await waitFor(() => expect(instances[0].setSeries).toHaveBeenCalledWith(2, { show: false }));
    rerender(<CurveChart series={series} xMode="step" hidden={new Set(["b"])} focused="a" />);
    expect(instances[0].setSeries).toHaveBeenCalledWith(1, { focus: true });
  });

  it("destroys the plot on unmount", async () => {
    const { unmount } = render(<CurveChart series={[flat("a", 1)]} xMode="step" />);
    await waitFor(() => expect(instances).toHaveLength(1));
    unmount();
    expect(instances[0].destroyed).toBe(true);
  });

  it("renders an empty frame without a canvas (jsdom, old browsers)", async () => {
    window.matchMedia = originalMatchMedia;
    const { container } = render(<CurveChart series={[flat("a", 1)]} xMode="step" height={150} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(instances).toHaveLength(0);
    expect(container.querySelector("[data-testid='curve-chart']")).toBeInTheDocument();
  });
});
