import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import MetricScatter from "../MetricScatter";
import MetricBarChart from "../MetricBarChart";
import type { ExperimentRow } from "../../types";

type RoCb = (entries: { contentRect: { width: number } }[]) => void;
const roCallbacks: RoCb[] = [];

beforeEach(() => {
  roCallbacks.length = 0;
  globalThis.ResizeObserver = class {
    constructor(cb: RoCb) { roCallbacks.push(cb); }
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const row = (i: number, metrics: Record<string, number>): ExperimentRow => ({
  idx: i, verstr: `0.0.1-dev.${i}`, code_verstr: `0.0.1-dev.${i}`, timestamp: null,
  note: null, branch: "main", base_version: "0.0.1", user_meta: null, metrics,
});
const ROWS = [row(1, { loss: 0.5, acc: 0.8 }), row(2, { loss: 0.3, acc: 0.9 })];

const resize = (width: number) =>
  act(() => roCallbacks.forEach((cb) => cb([{ contentRect: { width } }])));

describe("MetricScatter", () => {
  it("calls onSelect with the clicked point's run", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} onSelect={onSelect} />,
    );
    fireEvent.click(container.querySelectorAll(".recharts-scatter-symbol")[0]);
    expect(onSelect).toHaveBeenCalledWith(expect.stringMatching(/^0\.0\.1-dev\.[12]$/));
  });

  it("navigates to the run page by default", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/ws/w/app/my-app"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app" element={
            <MetricScatter rows={[ROWS[0]]} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />
          } />
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<div>run page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(container.querySelector(".recharts-scatter-symbol")!);
    expect(screen.getByText("run page")).toBeInTheDocument();
  });

  it("fills the width of its container", () => {
    const { container } = render(
      <MetricScatter rows={ROWS} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />,
    );
    resize(900);
    expect((container.querySelector(".recharts-wrapper") as HTMLElement).style.width).toBe("900px");
  });

  it("keeps tooltips for large point counts", () => {
    const many = Array.from({ length: 2500 }, (_, i) => row(i + 1, { loss: i, acc: i % 7 }));
    const { container } = render(
      <MetricScatter rows={many} metricCols={["loss", "acc"]} paramCols={[]} schema={null} />,
    );
    expect(container.querySelector(".recharts-tooltip-wrapper")).toBeInTheDocument();
  });
});

describe("MetricBarChart", () => {
  it("calls onSelect with the clicked bar's run", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <MetricBarChart rows={ROWS} metricCols={["acc"]} schema={null} onSelect={onSelect} />,
    );
    fireEvent.click(container.querySelectorAll(".recharts-bar-rectangle")[0]);
    // bars are sorted best-first: acc 0.9 is run 2
    expect(onSelect).toHaveBeenCalledWith("0.0.1-dev.2");
  });

  it("fills the width of its container", () => {
    const { container } = render(<MetricBarChart rows={ROWS} metricCols={["acc"]} schema={null} />);
    resize(700);
    expect((container.querySelector(".recharts-wrapper") as HTMLElement).style.width).toBe("700px");
  });
});
