/** Plan 20 A7/D12: a sweep whose trials all finished but number fewer than
 *  planned reads `16/20 · incomplete` — on the run page (status line and
 *  Fleet card), in the leaderboard row (total cell, else the experiment cell)
 *  and on a mobile card. A complete sweep and other runs are unchanged. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    experiment: vi.fn(),
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiSweep", () => ({ fetchSweep: vi.fn() }));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { fetchSweep } from "../../apiSweep";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import type { ExperimentDetail, RunStatus } from "../../types";
import { sweepIncompleteLabel } from "../../util/sweepProgress";
import Run from "../Run";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const OUTER = "0.0.2-rc.1";
const LABEL = "16/20 · incomplete";

function status(trials: number, extra: Partial<RunStatus> = {}): RunStatus {
  const kids = Array.from({ length: trials }, (_, i) => `0.0.2-dev.k${i}`);
  return {
    status: "created", exit_code: null, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
    children: kids, kind: "outer", depth: 0,
    tree_status: trials < 20 ? "created" : "succeeded", last_metric_at: null,
    sweep_planned: 20, sweep_trials: trials,
    fleet: {
      expected: 20, counts: { succeeded: trials, waiting: 20 - trials },
      children: kids.map((v) => ({ verstr: v, status: "succeeded", progress: null, progress_total: null })),
    },
    ...extra,
  };
}

function detail(st: RunStatus): ExperimentDetail {
  return {
    metadata: { verstr: OUTER, branch: "main", base_version: "0.0.1", timestamp: "2026-01-01T12:00:00Z" },
    metrics: {}, series: {}, log: [], patches: {}, status: st,
  } as unknown as ExperimentDetail;
}

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${OUTER}`]}>
      <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
    </MemoryRouter>,
  );
}

const sweepRow = (trials: number) => row(2, {
  kind: "outer", depth: 0, status: "created",
  tree_status: trials < 20 ? "created" : "succeeded",
  children: Array.from({ length: trials }, (_, i) => `k${i}`),
  child_counts: { succeeded: trials }, sweep_planned: 20, sweep_trials: trials,
});

function serve(rows: ReturnType<typeof row>[]) {
  m.experiments.mockResolvedValue(page(rows));
  m.experimentsPaged.mockResolvedValue({ rows, total: rows.length });
}

const rowOf = (verstr: string) =>
  [...document.querySelectorAll("tbody tr.row")].find((r) => r.textContent?.includes(verstr)) as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  vi.mocked(fetchSweep).mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("sweepIncompleteLabel", () => {
  it("names the trials of the planned size while the tree is created", () => {
    expect(sweepIncompleteLabel(status(16))).toBe(LABEL);
  });
  it("is null for a complete sweep, a running one, or a run without a plan", () => {
    expect(sweepIncompleteLabel(status(20))).toBeNull();
    expect(sweepIncompleteLabel(status(16, { tree_status: "running" }))).toBeNull();
    expect(sweepIncompleteLabel(status(16, { sweep_planned: null }))).toBeNull();
    expect(sweepIncompleteLabel({ kind: "single", status: "created", tree_status: "created" })).toBeNull();
  });
});

describe("the run page of a sweep", () => {
  it("says 16/20 · incomplete beside the created pill and in the Fleet card", async () => {
    m.experiment.mockResolvedValue(detail(status(16)));
    renderRun();
    await waitFor(() => expect(screen.getByText("Fleet")).toBeInTheDocument());
    const line = document.querySelector(".run-status-line") as HTMLElement;
    expect(line.querySelector(".status-pill")?.className).toContain("created");
    expect(within(line).getByText(LABEL)).toBeInTheDocument();
    expect(line.textContent).not.toContain("inner");
    const fleet = screen.getByText("Fleet").closest(".card") as HTMLElement;
    expect(within(fleet).getByText(LABEL)).toBeInTheDocument();
  });

  it("reads succeeded · 20/20 inner once every trial ran", async () => {
    m.experiment.mockResolvedValue(detail(status(20)));
    renderRun();
    await waitFor(() => expect(screen.getByText("Fleet")).toBeInTheDocument());
    const line = document.querySelector(".run-status-line") as HTMLElement;
    expect(line.querySelector(".status-pill")?.className).toContain("succeeded");
    expect(line.textContent).toContain("20/20 inner");
    expect(document.body.textContent).not.toContain("incomplete");
  });
});

describe("the leaderboard row of a sweep", () => {
  // Plan 22 G1: the count columns and the cell's "N inner" are gone.
  it("shows it in the experiment cell", async () => {
    serve([sweepRow(16), row(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    const cell = rowOf("0.0.2-dev.x").querySelector(".exp-cell .tree-roll") as HTMLElement;
    expect(cell.textContent).toBe(LABEL);
  });

  it("leaves a complete sweep's row as it was", async () => {
    serve([sweepRow(20), row(1)]);
    renderBoard();
    await screen.findByText("0.0.2-dev.x");
    expect(rowOf("0.0.2-dev.x").textContent).not.toContain("incomplete");
  });
});

describe("the mobile card of a sweep", () => {
  beforeEach(() => fakeMedia([NARROW_QUERY]));
  afterEach(dropFakeMedia);

  it("says 16/20 · incomplete on a line of its own, with no inner count (plan 22 G1)", async () => {
    serve([sweepRow(16), row(1)]);
    renderBoard();
    const list = await screen.findByRole("list", { name: "experiments" });
    expect(within(list).getByText(LABEL)).toHaveClass("lb-mcard-sweep");
    expect(within(list).queryByText(/^16 inner$/)).toBeNull();
  });
});
