/** Plan 20 B6 on the run page: an outer run lists its children once (the
 *  Status card has no `children` row; the fleet table labels them `@N name`),
 *  and a sweep's trials are listed by the Sweep card only. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), experiments: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiSweep", () => ({ fetchSweep: vi.fn() }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { fetchSweep, type SweepView } from "../../apiSweep";
import type { ExperimentDetail, FleetChild, RunStatus } from "../../types";
import Run from "../Run";

const mocked = api as unknown as Record<"experiment" | "experiments" | "metricsSchema", ReturnType<typeof vi.fn>>;
const OUTER = "0.0.2-rc.1";
const kids = ["0.0.2-dev.k1", "0.0.2-dev.k2", "0.0.2-dev.k3"];

const fleetChild = (v: string, i: number): FleetChild => ({
  verstr: v, status: "succeeded", progress: null, progress_total: null,
  idx: 3 + i, name: `k${i}`, params: { lr: i }, metrics: { lr: i, loss: 1 / (i + 1) }, last_step: null,
});

function detail(metadata: Record<string, unknown> = {}): ExperimentDetail {
  const status: RunStatus = {
    status: "created", exit_code: null, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
    children: kids, kind: "outer", depth: 0, tree_status: "succeeded", last_metric_at: null,
    fleet: { expected: 3, counts: { succeeded: 3 }, children: kids.map(fleetChild) },
  };
  return {
    metadata: { verstr: OUTER, branch: "main", base_version: "0.0.1", timestamp: "2026-01-01T12:00:00Z", ...metadata },
    metrics: {}, series: {}, log: [], patches: {}, status,
  } as unknown as ExperimentDetail;
}

const sweepView: SweepView = {
  sweep: OUTER,
  spec: { method: "grid", metric: { name: "loss", goal: "min" }, parameters: { lr: { values: [0, 1, 2] } } },
  trials: kids.map((v, i) => ({
    verstr: v, name: `k${i}`, trial: i, attempt: 0, status: "succeeded", params: { lr: i },
    value: 1 / (i + 1), metric_source: v, stopped_early: false,
  })),
  summary: { counts: { succeeded: 3 }, stopped_early: 0, trials: 3, best: null },
};

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${OUTER}`]}>
      <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
    </MemoryRouter>,
  );
}

const occurrences = (text: string) => document.body.textContent!.split(text).length - 1;
const childLinks = (v: string) => document.querySelectorAll(`a[href$="/run/${v}"]`).length;

beforeEach(() => {
  vi.clearAllMocks();
  mocked.metricsSchema.mockResolvedValue({});
  mocked.experiments.mockResolvedValue([]);
  vi.mocked(fetchSweep).mockResolvedValue(sweepView);
});

describe("outer run page", () => {
  it("lists each child once, by @N name, with no children row in Status", async () => {
    mocked.experiment.mockResolvedValue(detail());
    renderRun();
    await waitFor(() => expect(screen.getByText("Fleet")).toBeInTheDocument());
    expect(screen.queryByText("children")).toBeNull();
    for (const v of kids) {
      expect(occurrences(v)).toBe(0);
      expect(childLinks(v)).toBe(1);
    }
    expect(screen.getByRole("link", { name: "@3 k0" })).toBeInTheDocument();
  });

  it("lists a sweep's trials in the Sweep card only", async () => {
    mocked.experiment.mockResolvedValue(detail({ sweep: sweepView.spec }));
    renderRun();
    await waitFor(() => expect(screen.getAllByTestId("sweep-trial")).toHaveLength(3));
    expect(screen.getByText("Fleet")).toBeInTheDocument();
    for (const v of kids) {
      expect(occurrences(v)).toBe(0);
      expect(childLinks(v)).toBe(1);
    }
    expect(screen.getByRole("link", { name: "@3 k0" })).toBeInTheDocument();
  });
});
