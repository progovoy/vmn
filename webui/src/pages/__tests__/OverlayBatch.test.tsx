import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("uplot", async () => await import("../../components/__tests__/fakeUPlot"));
vi.mock("../../api", () => ({
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiSeries", () => ({
  fetchSeriesBatch: vi.fn(),
  fetchRunStatuses: vi.fn(),
}));

import { fetchRunStatuses, fetchSeriesBatch } from "../../apiSeries";
import {
  enableCanvas, instances, resetInstances,
} from "../../components/__tests__/fakeUPlot";
import Overlay from "../Overlay";

const mockedBatch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;
const mockedStatuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;

const curve = (v0: number) => [0, 1, 2].map((i) => ({ step: i, value: v0 - i * 0.1, ts: null }));

function batch(runs: string[], extra: Record<string, unknown> = {}) {
  return {
    series: Object.fromEntries(runs.map((v, i) => [v, { loss: curve(1 + i), acc: curve(i) }])),
    series_total: {},
    missing: [],
    ...extra,
  };
}

function renderOverlay(runs: string[]) {
  return render(
    <MemoryRouter initialEntries={[`/ws/w/app/my-app/overlay?runs=${runs.join(",")}`]}>
      <Routes><Route path="/ws/:ws/app/:app/overlay" element={<Overlay />} /></Routes>
    </MemoryRouter>,
  );
}

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  mockedStatuses.mockResolvedValue({});
});
afterEach(() => {
  vi.useRealTimers();
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("Overlay batch loading", () => {
  it("fetches every run's series in one batch request", async () => {
    const runs = ["0.0.1-dev.a", "0.0.1-dev.b", "0.0.1-dev.c"];
    mockedBatch.mockResolvedValue(batch(runs));
    renderOverlay(runs);
    await screen.findByText("loss");
    expect(mockedBatch).toHaveBeenCalledTimes(1);
    expect(mockedBatch).toHaveBeenCalledWith("w", "my-app", runs, null, 1000);
  });

  it("shows the error when the batch request fails", async () => {
    mockedBatch.mockRejectedValue(Object.assign(new Error("Not Found"), { status: 404 }));
    renderOverlay(["a", "b"]);
    expect(await screen.findByText(/Not Found/)).toBeInTheDocument();
  });

  it("lists runs the server could not find", async () => {
    mockedBatch.mockResolvedValue(batch(["a"], { missing: ["gone"] }));
    renderOverlay(["a", "gone"]);
    expect(await screen.findByText(/not found: gone/)).toBeInTheDocument();
  });

  it("gives each chart one series per run", async () => {
    const runs = ["a", "b", "c"];
    mockedBatch.mockResolvedValue(batch(runs));
    renderOverlay(runs);
    await waitFor(() => expect(instances).toHaveLength(2)); // loss + acc
    for (const u of instances) expect((u.opts.series as unknown[]).length).toBe(4);
  });
});

describe("Overlay legend", () => {
  it("toggles a run off and on by clicking it", async () => {
    mockedBatch.mockResolvedValue(batch(["a", "b"]));
    renderOverlay(["a", "b"]);
    const item = await screen.findByRole("button", { name: "b" });
    expect(item).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(item);
    expect(item).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    await waitFor(() => expect(instances[0].setSeries).toHaveBeenCalledWith(2, { show: false }));
  });

  it("highlights a run while its legend entry is hovered", async () => {
    mockedBatch.mockResolvedValue(batch(["a", "b"]));
    renderOverlay(["a", "b"]);
    const item = await screen.findByRole("button", { name: "a" });
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    fireEvent.mouseEnter(item);
    await waitFor(() => expect(instances[0].setSeries).toHaveBeenCalledWith(1, { focus: true }));
  });
});

describe("Overlay polling", () => {
  it("re-fetches while any overlaid run is still running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedBatch.mockResolvedValue(batch(["a", "b"]));
    mockedStatuses.mockResolvedValue({
      a: { status: "running", heartbeat_interval_sec: 10 }, b: { status: "succeeded" },
    });
    renderOverlay(["a", "b"]);
    await screen.findByText("loss");
    expect(mockedBatch).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5100); });
    expect(mockedBatch).toHaveBeenCalledTimes(2);
  });

  it("does not poll once every run has finished", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedBatch.mockResolvedValue(batch(["a"]));
    mockedStatuses.mockResolvedValue({ a: { status: "succeeded" } });
    renderOverlay(["a"]);
    await screen.findByText("loss");
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(mockedBatch).toHaveBeenCalledTimes(1);
  });
});
