import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../apiRun", () => ({ runLog: vi.fn() }));

import { api } from "../api";
import { runLog } from "../apiRun";
import Run from "../pages/Run";
import Overlay from "../pages/Overlay";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};
const mockedRunLog = runLog as unknown as ReturnType<typeof vi.fn>;

const T0 = Date.UTC(2026, 0, 1, 12, 0, 0);
const iso = (s: number) => new Date(T0 + s * 1000).toISOString();

function detail(extra: Record<string, unknown> = {}) {
  return {
    metadata: { verstr: "0.0.1-dev.a", branch: "main", base_version: "0.0.1", base_commit: "abc1234" },
    params: { model: "resnet50", lr: 0.001 },
    metrics: { loss: 0.1, sys_rss_mb: 2048 },
    series: {
      loss: [0, 1, 2].map((i) => ({ step: i, value: 1 - i * 0.1, ts: iso(i) })),
      sys_rss_mb: [0, 1, 2].map((i) => ({ step: null, value: 2000 + i, ts: iso(i * 30) })),
    },
    series_total: { loss: 3, sys_rss_mb: 3 },
    log_tail: [
      { timestamp: iso(5), type: "note", text: "tail-entry-b" },
      { timestamp: iso(6), type: "note", text: "tail-entry-c" },
    ],
    log_total: 3,
    patches: {},
    ...extra,
  };
}

function renderAt(path: string, route: string, el: JSX.Element) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path={route} element={el} /></Routes>
    </MemoryRouter>,
  );
}
const renderRun = () =>
  renderAt("/ws/w/app/app/run/0.0.1-dev.a", "/ws/:ws/app/:app/run/:verstr", <Run />);

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("Run page", () => {
  it("renders the log tail and pages older entries through the log endpoint", async () => {
    mockedApi.experiment.mockResolvedValue(detail());
    mockedRunLog.mockResolvedValue({
      entries: [{ timestamp: iso(1), type: "note", text: "older-entry-a" }], total: 3,
    });
    renderRun();
    await screen.findByText(/tail-entry-b/);
    expect(screen.queryByText(/older-entry-a/)).toBeNull();
    fireEvent.click(screen.getByText(/load older/));
    await screen.findByText(/older-entry-a/);
    expect(mockedRunLog).toHaveBeenCalledWith("w", "app", "0.0.1-dev.a", 0, 1);
    expect(screen.queryByText(/load older/)).toBeNull();
  });

  it("still renders a full `log` from older servers", async () => {
    const d = detail({ log: [{ timestamp: iso(1), type: "note", text: "legacy-entry" }] });
    delete (d as Record<string, unknown>).log_tail;
    delete (d as Record<string, unknown>).log_total;
    mockedApi.experiment.mockResolvedValue(d);
    renderRun();
    await screen.findByText(/legacy-entry/);
  });

  it("shows verbatim params, strings included", async () => {
    mockedApi.experiment.mockResolvedValue(detail());
    renderRun();
    await screen.findByText("resnet50");
    expect(screen.getByText("model")).toBeInTheDocument();
  });

  it("keeps system metrics off the training chart until toggled", async () => {
    mockedApi.experiment.mockResolvedValue(detail());
    renderRun();
    await screen.findByText("training curves");
    expect(screen.queryByText("system metrics")).toBeNull();
    fireEvent.click(screen.getByText(/show system metrics/));
    expect(screen.getByText("system metrics")).toBeInTheDocument();
  });
});

describe("Overlay page", () => {
  it("caps the number of overlaid runs", async () => {
    const runs = Array.from({ length: 30 }, (_, i) => `0.0.1-dev.r${i}`);
    mockedApi.experiment.mockImplementation((_w: string, _a: string, v: string) =>
      Promise.resolve({ ...detail(), metadata: { verstr: v } }));
    renderAt(
      `/ws/w/app/app/overlay?runs=${runs.join(",")}`, "/ws/:ws/app/:app/overlay", <Overlay />,
    );
    await waitFor(() => expect(mockedApi.experiment).toHaveBeenCalled());
    expect(mockedApi.experiment.mock.calls.length).toBe(20);
    expect(screen.getByText(/showing the first 20 of 30/)).toBeInTheDocument();
  });
});
