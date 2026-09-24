import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import MetricScatter from "../MetricScatter";
import MetricBarChart from "../MetricBarChart";
import type { ExperimentRow } from "../../types";

type RoCb = (entries: { contentRect: { width: number } }[]) => void;
const roCallbacks: RoCb[] = [];

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  roCallbacks.length = 0;
  globalThis.ResizeObserver = class {
    constructor(cb: RoCb) { roCallbacks.push(cb); }
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const row = (i: number, metrics: Record<string, number>): ExperimentRow => ({
  idx: i, verstr: `0.0.1-dev.${i}`, code_verstr: `0.0.1-dev.${i}`, timestamp: null,
  note: null, branch: "main", base_version: "0.0.1", user_meta: null, metrics,
});
const ROWS = [row(1, { loss: 0.5, acc: 0.8 }), row(2, { loss: 0.3, acc: 0.9 })];

async function plot() {
  await waitFor(() => expect(instances.length).toBeGreaterThan(0));
  return instances[instances.length - 1];
}

describe("MetricScatter", () => {
  it("calls onSelect with the point nearest a click", async () => {
    const onSelect = vi.fn();
    render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} onSelect={onSelect} />,
    );
    const u = await plot();
    act(() => u.moveCursor(0.301, 0.899)); // fake posToVal is the identity
    fireEvent.click(screen.getByTestId("scatter-chart"));
    expect(onSelect).toHaveBeenCalledWith("0.0.1-dev.2");
  });

  it("navigates to the run page by default", async () => {
    render(
      <MemoryRouter initialEntries={["/ws/w/app/my-app"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app" element={
            <MetricScatter rows={[ROWS[0]]} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />
          } />
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<div>run page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const u = await plot();
    act(() => u.moveCursor(0.5, 0.8));
    fireEvent.click(screen.getByTestId("scatter-chart"));
    expect(screen.getByText("run page")).toBeInTheDocument();
  });

  it("does nothing when clicked away from every point", async () => {
    const onSelect = vi.fn();
    render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} onSelect={onSelect} />,
    );
    await plot();
    fireEvent.click(screen.getByTestId("scatter-chart"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("fills the width of its container", async () => {
    render(<MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />);
    const u = await plot();
    act(() => roCallbacks.forEach((cb) => cb([{ contentRect: { width: 900 } }])));
    expect(u.setSize).toHaveBeenCalledWith(expect.objectContaining({ width: 900 }));
  });

  it("keeps tooltips for large point counts", async () => {
    const many = Array.from({ length: 2500 }, (_, i) => row(i + 1, { loss: i, acc: i % 7 }));
    render(<MetricScatter rows={many} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />);
    const u = await plot();
    act(() => u.moveCursor(1234, 2));
    expect(screen.getByTestId("scatter-tooltip").textContent).toContain("@1235");
  });
});

describe("MetricBarChart", () => {
  it("calls onSelect with the clicked bar's run", () => {
    const onSelect = vi.fn();
    render(<MetricBarChart rows={ROWS} metricCols={["acc"]} schema={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId("bar")[0]);
    // bars are sorted best-first: acc 0.9 is run 2
    expect(onSelect).toHaveBeenCalledWith("0.0.1-dev.2");
  });

  it("sizes bars relative to the largest value, so they fill any width", () => {
    render(<MetricBarChart rows={ROWS} metricCols={["acc"]} schema={null} />);
    const fills = screen.getAllByTestId("bar-fill").map((el) => el.style.width);
    expect(fills).toEqual(["100%", `${(0.8 / 0.9) * 100}%`]);
  });

  it("marks the best bar and gives every bar a tooltip", () => {
    render(<MetricBarChart rows={ROWS} metricCols={["acc"]} schema={null} />);
    const [best, other] = screen.getAllByTestId("bar-fill");
    expect(best.style.background).toBe("var(--good)");
    expect(other.style.background).toBe("var(--accent)");
    expect(screen.getAllByTestId("bar")[0].getAttribute("title")).toBe("0.0.1-dev.2: 0.9");
  });
});
