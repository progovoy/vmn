import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("uplot", async () => await import("../components/__tests__/fakeUPlot"));

import { enableCanvas, resetInstances } from "../components/__tests__/fakeUPlot";
import ParamPlots from "../components/ParamPlots";
import MetricBarChart from "../components/MetricBarChart";
import RunOutput from "../components/RunOutput";
import { FleetCard, ParamsCard } from "../pages/RunSections";
import type { ExperimentRow, Fleet } from "../types";

const row = (i: number, metrics: Record<string, number>): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", metrics,
});
const rows = [row(1, { loss: 0.5 }), row(2, { loss: 0.4 })];

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("log line"))));
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
  vi.unstubAllGlobals();
});

describe("in-page section headings", () => {
  it("leaderboard charts carry no label repeating the active chart tab", () => {
    const { container } = render(<ParamPlots rows={rows} metricCols={["loss"]} schema={null} />);
    expect(screen.queryByText(/metrics across runs/i)).toBeNull();
    expect(container.querySelector(".eyebrow")).toBeNull();
    render(<MetricBarChart rows={rows} metricCols={["loss"]} schema={null} />);
    expect(screen.queryByText(/metric bar chart/i)).toBeNull();
  });

  it("run sections are sentence-case h2 headings, not eyebrows", () => {
    const fleet: Fleet = { expected: 1, counts: { running: 1 }, children: [] } as unknown as Fleet;
    const { container } = render(
      <MemoryRouter>
        <ParamsCard params={{ lr: 0.1 }} />
        <FleetCard fleet={fleet} runUrl={(v) => v} />
        <RunOutput artifacts={[{ name: "outputs/output.log", size: 8 }]} downloadUrl={(f) => f} />
      </MemoryRouter>,
    );
    for (const name of ["Parameters", "Fleet", "Output"]) {
      const h = screen.getByRole("heading", { level: 2, name });
      expect(h).toHaveClass("section-title");
    }
    expect(container.querySelector(".eyebrow")).toBeNull();
  });
});
