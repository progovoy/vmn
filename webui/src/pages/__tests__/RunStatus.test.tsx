import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Polyfill ResizeObserver for jsdom (recharts needs it)
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { api } from "../../api";
import type { ExperimentDetail, RunState, RunStatus } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

function status(state: RunState, extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: state,
    exit_code: null,
    started_at: "2026-01-01T12:00:00Z",
    finished_at: null,
    heartbeat: "2026-01-01T12:00:30Z",
    duration_sec: 90,
    pid: 4242,
    host: "gpu0",
    command: ["python", "train.py"],
    stale_sec: null,
    parent: null,
    children: [],
    kind: "single",
    depth: 0,
    tree_status: null,
    last_metric_at: null,
    ...extra,
  };
}

function makeDetail(st?: RunStatus): ExperimentDetail {
  return {
    metadata: {
      verstr: "0.0.2-rc.1",
      branch: "main",
      base_version: "0.0.1",
      base_commit: "abc1234567890",
      timestamp: "2026-01-01T12:00:00Z",
      note: "",
    },
    metrics: {},
    series: {},
    log: [{ timestamp: "2026-01-01T12:00:00Z", type: "create" }],
    patches: {},
    ...(st ? { status: st } : {}),
  };
}

function renderRun() {
  return render(
    <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.2-rc.1"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("Run status block", () => {
  it("shows the pill, exit code, duration, pid/host and command", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(status("failed", { exit_code: 3, finished_at: "2026-01-01T12:01:30Z" }))
    );

    renderRun();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    const pill = document.querySelector(".status-pill") as HTMLElement;
    expect(pill.className).toContain("failed");
    expect(pill.getAttribute("aria-label")).toContain("exit 3");
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("90s")).toBeInTheDocument();
    expect(screen.getByText(/4242/)).toBeInTheDocument();
    expect(screen.getByText(/gpu0/)).toBeInTheDocument();
    expect(screen.getByText("python train.py")).toBeInTheDocument();
  });

  it("reports how long a stuck run has been missing its heartbeat", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(status("stuck", { stale_sec: 600 }))
    );

    renderRun();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    expect(screen.getByText(/no heartbeat for 10m/)).toBeInTheDocument();
  });

  it("renders parent and children links to the sibling runs", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(status("succeeded", {
        kind: "inner", depth: 1, parent: "0.0.1-rc.1",
        children: ["0.0.3-rc.1", "0.0.4-rc.1"],
      }))
    );

    renderRun();

    await waitFor(() => expect(screen.getByText("parent")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "0.0.1-rc.1" }))
      .toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.1-rc.1");
    expect(screen.getByText("children")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0.0.4-rc.1" }))
      .toHaveAttribute("href", "/ws/test/app/my-app/run/0.0.4-rc.1");
  });

  it("omits the status block when the server reports no run status", async () => {
    mockedApi.experiment.mockResolvedValue(makeDetail());

    renderRun();

    await waitFor(() => expect(screen.getByText("metadata")).toBeInTheDocument());
    expect(document.querySelector(".status-pill")).toBeNull();
  });

  it("keeps the run log's exit line", async () => {
    const detail = makeDetail(status("succeeded", { exit_code: 0 }));
    detail.log = [{
      timestamp: "2026-01-01T12:01:30Z", type: "run",
      command: ["python", "train.py"], exit_code: 0, duration_sec: 90,
    }];
    mockedApi.experiment.mockResolvedValue(detail);

    renderRun();

    await waitFor(() =>
      expect(screen.getByText(/exit 0 in 90s/)).toBeInTheDocument()
    );
  });
});

/** Advance fake time with React's work flushed, so the poll timer is armed
 *  before the clock moves. */
const tick = (ms: number) =>
  act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("Run auto-refresh", () => {
  it("polls a running experiment and stops once it finishes", async () => {
    vi.useFakeTimers();
    mockedApi.experiment.mockResolvedValue(makeDetail(status("running")));

    renderRun();
    await tick(0);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(1);

    await tick(15000);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(2);

    mockedApi.experiment.mockResolvedValue(
      makeDetail(status("succeeded", { exit_code: 0 }))
    );
    await tick(15000);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(3);

    await tick(60000);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it("follows the run's own heartbeat interval", async () => {
    vi.useFakeTimers();
    mockedApi.experiment.mockResolvedValue(
      makeDetail(status("running", { heartbeat_interval_sec: 60 }))
    );

    renderRun();
    await tick(0);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(1);

    // Half of a 60s heartbeat — the 15s default goes by without a refetch.
    await tick(15000);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(1);
    await tick(15000);
    expect(mockedApi.experiment).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});
