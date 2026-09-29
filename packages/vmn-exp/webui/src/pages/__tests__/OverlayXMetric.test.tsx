import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("uplot", async () => await import("../../components/__tests__/fakeUPlot"));
vi.mock("../../api", () => ({
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiSeries", () => ({
  fetchSeriesBatch: vi.fn(),
  fetchRunStatuses: vi.fn(),
}));

import { fetchRunStatuses, fetchSeriesBatch } from "../../apiSeries";
import { enableCanvas, resetInstances } from "../../components/__tests__/fakeUPlot";
import Overlay from "../Overlay";

const mockedBatch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;
const mockedStatuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;

const RUNS = ["0.0.1-dev.a", "0.0.1-dev.b"];
const curve = () => [0, 1, 2].map((i) => ({ step: i, value: 1 - i * 0.1, ts: null }));

function batch(stepMetrics: Record<string, Record<string, string>> = {}) {
  return {
    series: Object.fromEntries(RUNS.map((v) => [v, { loss: curve(), acc: curve(), epoch: curve() }])),
    series_total: {},
    step_metrics: stepMetrics,
    missing: [],
  };
}

function renderOverlay() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/w/app/my-app/overlay?runs=${RUNS.join(",")}`]}>
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
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("Overlay x metric", () => {
  it("joins declared metrics on their step metric across runs", async () => {
    mockedBatch.mockResolvedValue(batch({ [RUNS[0]]: { loss: "epoch" } }));
    renderOverlay();
    await screen.findByText("loss");
    await waitFor(() => expect(mockedBatch).toHaveBeenCalledWith(
      "w", "my-app", RUNS, ["loss"], 1000, { loss: "epoch" },
    ));
  });

  it("a picked x metric joins every shared metric on it", async () => {
    mockedBatch.mockResolvedValue(batch());
    renderOverlay();
    await screen.findByText("loss");
    expect(mockedBatch).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("combobox", { name: /x axis metric/i }), { target: { value: "epoch" } });
    await waitFor(() => expect(mockedBatch).toHaveBeenCalledWith(
      "w", "my-app", RUNS, ["acc", "loss"], 1000, { acc: "epoch", loss: "epoch" },
    ));
  });

  it("shows a failed join and keeps the overlay drawn", async () => {
    mockedBatch.mockImplementation((_ws, _app, _runs, _metrics, _points, xMap) =>
      xMap ? Promise.reject(new Error("join exploded")) : Promise.resolve(batch({ [RUNS[0]]: { loss: "epoch" } })));
    renderOverlay();
    expect(await screen.findByText(/join exploded/)).toBeInTheDocument();
    expect(screen.getByText("loss")).toBeInTheDocument();
  });
});
