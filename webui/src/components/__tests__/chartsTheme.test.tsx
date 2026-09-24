import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { act, render, waitFor } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import CurveChart from "../CurveChart";
import MetricScatter from "../MetricScatter";
import { THEME_EVENT } from "../../hooks/useTheme";
import type { ExperimentRow } from "../../types";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
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

const themeChanged = () => act(() => { window.dispatchEvent(new Event(THEME_EVENT)); });

describe("charts follow a theme switch", () => {
  it("rebuilds a curve chart so it re-reads the palette", async () => {
    render(
      <CurveChart
        series={[{ key: "a", label: "a", color: "#123456", xs: Float64Array.from([0, 1]), ys: Float64Array.from([1, 2]) }]}
        xMode="step"
      />,
    );
    await waitFor(() => expect(instances).toHaveLength(1));
    themeChanged();
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(instances[0].destroyed).toBe(true);
  });

  it("rebuilds a scatter chart so it re-reads the palette", async () => {
    const rows: ExperimentRow[] = [1, 2].map((i) => ({
      idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
      branch: "main", base_version: "1", user_meta: null, metrics: { loss: i, acc: i / 10 },
    }));
    render(<MetricScatter rows={rows} metricCols={["loss", "acc"]} paramCols={[]} schema={{}} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    themeChanged();
    await waitFor(() => expect(instances).toHaveLength(2));
  });
});
