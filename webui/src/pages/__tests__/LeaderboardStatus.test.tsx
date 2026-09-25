import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiments: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

vi.mock("../../components/ParamPlots", () => ({
  default: () => <div data-testid="param-plots" />,
}));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

// jsdom gives the scroll container zero height, so the real virtualizer would
// render no rows. Render them all instead — this suite is about row content.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48,
      })),
  }),
}));

import { api } from "../../api";
import type { ExperimentRow, RunState } from "../../types";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

function row(
  idx: number, status: RunState, extra: Partial<ExperimentRow> = {}
): ExperimentRow {
  return {
    idx,
    verstr: `0.0.${idx}-rc.1`,
    code_verstr: `0.0.${idx}`,
    timestamp: "2026-01-01T12:00:00Z",
    note: null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    metrics: { loss: 0.5 },
    status,
    exit_code: null,
    started_at: null,
    finished_at: null,
    heartbeat: null,
    duration_sec: null,
    pid: null,
    host: null,
    command: null,
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

function renderLeaderboard() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const cellOf = (verstr: string) =>
  screen.getByText(verstr).closest("td") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("Leaderboard status column", () => {
  it("renders a status pill per row", async () => {
    mockedApi.experiments.mockResolvedValue([
      row(1, "succeeded"), row(2, "failed", { exit_code: 1 }),
      row(3, "running"), row(4, "stuck", { stale_sec: 600 }),
    ]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    const pills = document.querySelectorAll(".status-pill");
    expect(pills).toHaveLength(4);
    expect([...pills].map((p) => p.className)).toEqual([
      "status-pill succeeded", "status-pill failed",
      "status-pill running", "status-pill stuck",
    ]);
  });

  it("hides inner runs from the list and shows the child count on the outer", async () => {
    mockedApi.experiments.mockResolvedValue([
      row(1, "running", {
        kind: "outer", children: ["0.0.2-rc.1", "0.0.3-rc.1"], tree_status: "running",
      }),
      row(2, "succeeded", { kind: "inner", depth: 1, parent: "0.0.1-rc.1" }),
      row(3, "failed", { kind: "inner", depth: 1, parent: "0.0.1-rc.1", exit_code: 1 }),
    ]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());

    const outer = cellOf("0.0.1-rc.1");
    expect(outer.querySelector(".nest-mark")).toBeNull();
    expect(outer.querySelector(".tree-roll")?.textContent).toContain("2 inner");

    // Inner runs are filtered from the default list view
    expect(screen.queryByText("0.0.2-rc.1")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0.3-rc.1")).not.toBeInTheDocument();
  });

  it("shows the subtree rollup on an outer row when it differs", async () => {
    mockedApi.experiments.mockResolvedValue([
      row(1, "succeeded", {
        kind: "outer", children: ["0.0.2-rc.1"], tree_status: "failed",
      }),
      row(2, "failed", { kind: "inner", depth: 1, parent: "0.0.1-rc.1" }),
    ]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    expect(cellOf("0.0.1-rc.1").querySelector(".tree-roll")?.textContent)
      .toContain("tree failed");
  });

  it("omits the rollup when the subtree matches the row's own status", async () => {
    mockedApi.experiments.mockResolvedValue([
      row(1, "failed", {
        kind: "outer", children: ["0.0.2-rc.1"], tree_status: "failed",
      }),
    ]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    const roll = cellOf("0.0.1-rc.1").querySelector(".tree-roll");
    expect(roll?.textContent).toContain("1 inner");
    expect(roll?.textContent).not.toContain("tree");
  });
});

describe("Leaderboard status filter", () => {
  it("shows exactly the rows the server returned for the picked statuses", async () => {
    mockedApi.experiments.mockResolvedValue([
      row(1, "succeeded"), row(2, "running"), row(3, "stuck"),
    ]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText(/3\s*runs/)).toBeInTheDocument());
    expect(document.querySelectorAll(".status-pill")).toHaveLength(3);

    mockedApi.experiments.mockResolvedValue([row(2, "running"), row(3, "stuck")]);
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    fireEvent.click(screen.getByRole("button", { name: "stuck" }));

    await waitFor(() =>
      expect(document.querySelectorAll(".status-pill")).toHaveLength(2)
    );
    expect(screen.queryByText("0.0.1-rc.1")).not.toBeInTheDocument();
    expect(screen.getByText("0.0.2-rc.1")).toBeInTheDocument();
    // The toggles must survive the narrowed response, or there is no way back.
    expect(screen.getByRole("button", { name: "succeeded" })).toBeInTheDocument();
  });

  it("requests the picked statuses from the server", async () => {
    mockedApi.experiments.mockResolvedValue([row(1, "running")]);

    renderLeaderboard();

    await waitFor(() => expect(screen.getByText(/1\s*runs/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "running" }));

    await waitFor(() =>
      expect(mockedApi.experiments).toHaveBeenLastCalledWith(
        "test", "my-app", "timestamp", "running"
      )
    );
  });
});

/** Advance fake time with React's work flushed, so the poll timer is armed
 *  before the clock moves. */
const tick = (ms: number) =>
  act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("Leaderboard auto-refresh", () => {
  it("polls while a row is running and stops once none are", async () => {
    vi.useFakeTimers();
    mockedApi.experiments.mockResolvedValue([row(1, "running")]);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderLeaderboard();
    await tick(0);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);

    mockedApi.experiments.mockResolvedValue([row(1, "succeeded")]);
    await tick(15000);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(2);

    await tick(60000);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("follows the rows' heartbeat interval instead of a fixed 5s", async () => {
    vi.useFakeTimers();
    mockedApi.experiments.mockResolvedValue([
      row(1, "running", { heartbeat_interval_sec: 10 }),
    ]);

    renderLeaderboard();
    await tick(0);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);

    // A 10s heartbeat floors at the 5s minimum, so it still feels live.
    await tick(5000);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("stops polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("hidden");
    mockedApi.experiments.mockResolvedValue([row(1, "running")]);

    renderLeaderboard();
    await tick(0);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);

    await tick(60000);
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
    vi.useRealTimers();
  });
});
