/**
 * Outer runs report tree_status as the primary status pill.
 *
 * StatusCard: for kind === "outer", tree_status is the MAIN pill; the run's
 * own status is shown as secondary ONLY when it is failed/stuck or differs
 * from tree while running.
 *
 * LeaderboardRow: tree pill is primary for outers.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    experiment: vi.fn(),
    experiments: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({
  default: () => <div data-testid="param-plots" />,
}));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
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
import type { ExperimentDetail, ExperimentRow, RunState, RunStatus } from "../../types";
import Run from "../Run";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
  experiments: ReturnType<typeof vi.fn>;
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
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.2-rc.1"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

function lbRow(
  idx: number, st: RunState, extra: Partial<ExperimentRow> = {},
): ExperimentRow {
  return {
    idx,
    verstr: `0.0.${idx}-rc.1`,
    code_verstr: `0.0.${idx}`,
    timestamp: "2026-01-01T12:00:00Z",
    note: null,
    branch: "main",
    base_version: "0.0.1",
    metrics: {},
    status: st,
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

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("StatusCard for outer runs", () => {
  it("shows tree_status as the primary pill for an outer run", async () => {
    // Container outer: own status "created", tree_status "succeeded"
    mockedApi.experiment.mockResolvedValue(
      makeDetail(
        status("created", {
          kind: "outer",
          children: ["c1", "c2"],
          tree_status: "succeeded",
        }),
      ),
    );
    renderRun();
    await waitFor(() => expect(screen.getByText("Status")).toBeInTheDocument());
    // The primary pill should show tree_status (succeeded), not "created"
    const pill = document.querySelector(".status-pill") as HTMLElement;
    expect(pill.className).toContain("succeeded");
  });

  it("shows own status as secondary when outer failed but tree succeeded", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(
        status("failed", {
          kind: "outer",
          exit_code: 1,
          children: ["c1"],
          tree_status: "failed",
        }),
      ),
    );
    renderRun();
    await waitFor(() => expect(screen.getByText("Status")).toBeInTheDocument());
    // When the outer itself failed, it shows up
    const pill = document.querySelector(".status-pill") as HTMLElement;
    expect(pill.className).toContain("failed");
  });

  it("does not show secondary own-status when outer is just a container", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(
        status("created", {
          kind: "outer",
          children: ["c1", "c2"],
          tree_status: "succeeded",
        }),
      ),
    );
    renderRun();
    await waitFor(() => expect(screen.getByText("Status")).toBeInTheDocument());
    // Should not show "created" as any pill since it's just a container
    const pills = document.querySelectorAll(".status-pill");
    const texts = [...pills].map((p) => p.textContent);
    expect(texts).not.toContain("created");
  });

  it("leaves single/inner runs unchanged", async () => {
    mockedApi.experiment.mockResolvedValue(
      makeDetail(
        status("succeeded", { kind: "single" }),
      ),
    );
    renderRun();
    await waitFor(() => expect(screen.getByText("Status")).toBeInTheDocument());
    const pill = document.querySelector(".status-pill") as HTMLElement;
    expect(pill.className).toContain("succeeded");
  });
});

describe("LeaderboardRow for outer runs", () => {
  it("shows tree_status pill as primary for outers in the status column", async () => {
    mockedApi.experiments.mockResolvedValue([
      lbRow(1, "created", {
        kind: "outer",
        children: ["0.0.2-rc.1"],
        tree_status: "succeeded",
      }),
    ]);
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    // The status pill should show tree_status
    const pills = document.querySelectorAll(".status-pill");
    expect(pills).toHaveLength(1);
    expect(pills[0].className).toContain("succeeded");
  });

  it("keeps single run status unchanged in status column", async () => {
    mockedApi.experiments.mockResolvedValue([
      lbRow(1, "failed", { exit_code: 1, kind: "single" }),
    ]);
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    const pills = document.querySelectorAll(".status-pill");
    expect(pills).toHaveLength(1);
    expect(pills[0].className).toContain("failed");
  });
});
