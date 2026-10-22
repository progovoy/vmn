/** An outer run's page paints at once (production: 27k inner runs on S3):
 *  its header and tabs come from the index's row of it (a board's cached
 *  row, else a one-row index lookup), never waiting for the run detail (S3
 *  reads) or the subtree's summary; the Runs tab lists inner runs while the
 *  summary is still pending; the detail is read only where it is used. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../../api", () => ({
  api: {
    experiment: vi.fn(), experiments: vi.fn(), metricsSchema: vi.fn(),
    experimentsPaged: vi.fn(),
    facets: vi.fn(() => new Promise(() => {})),
    experimentGroups: vi.fn(() => Promise.reject(new Error("no groups"))),
    experimentsColumns: vi.fn(() => new Promise(() => {})),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));
vi.mock("../../../apiShell", () => ({ apiShell: { appStatus: vi.fn() } }));
vi.mock("../../../apiSeries", () => ({ fetchRunStatuses: vi.fn() }));
vi.mock("../../../components/TrainingCurves", () => ({ default: () => null }));
vi.mock("../../../components/RunChanges", () => ({ default: () => <div>changes stub</div> }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({
      index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
    })),
  }),
}));

import { api } from "../../../api";
import { jobSummary } from "../../../apiJob";
import { apiShell } from "../../../apiShell";
import { fetchRunStatuses } from "../../../apiSeries";
import { createQueryClient } from "../../../queryClient";
import { rowsKey } from "../../../queries";
import { FakeSource } from "../../../hooks/__tests__/fakeEventSource";
import type { ExperimentDetail, ExperimentRow } from "../../../types";
import Run from "../../Run";
import { JOB } from "./jobFixture";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});

const jobRow = (): ExperimentRow => ({
  idx: 36, verstr: JOB, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z", note: null,
  branch: "main", base_version: "0.0.1", metrics: {}, name: "lr_layers_grid",
  status: "succeeded", tree_status: "running", kind: "outer", depth: 0, children: ["k1"],
  command: ["python", "sweep.py"],
  job: {
    total: 27000, counts: { running: 40, waiting: 548, succeeded: 26409, failed: 3, stuck: 0 },
    done: 26412, expected: 27000, progress: 0.978, failed_pct: 0.01, throughput_per_min: 41,
    eta_sec: 840, metric: null, best: null, best_verstr: null, spread: [],
  },
} as ExperimentRow);

const inner = (i: number): ExperimentRow => ({
  idx: 100 + i, verstr: `0.0.2-dev.t${i}`, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z",
  note: null, branch: "main", base_version: "0.0.1", metrics: { loss: i / 10 }, name: `trial-${i}`,
  status: "succeeded", kind: "inner", depth: 1, parent: JOB,
} as ExperimentRow);

function renderRun(search = "", cachedRow = true) {
  const client = createQueryClient();
  if (cachedRow) client.setQueryData(rowsKey("test", "my-app", { top: "jobs" }), { rows: [jobRow()], total: 1 });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
        <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue([]);
  m.experiment.mockImplementation(never);
  vi.mocked(jobSummary).mockImplementation(never);
  vi.mocked(apiShell.appStatus).mockImplementation(never);
  // The one-row index lookup of the job finds nothing; the scoped board's rows.
  vi.mocked(fetchRunStatuses).mockResolvedValue({});
  m.experimentsPaged.mockImplementation((_ws: string, _app: string, opts: { scope?: string }) => (
    Promise.resolve(opts.scope ? { rows: [inner(1), inner(2)], total: 27000 } : { rows: [], total: 0 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("an outer run's first paint", () => {
  it("shows its header and tabs from the cached row while the detail and summary never answer", async () => {
    renderRun();
    expect(await screen.findByRole("tablist", { name: "Outer run" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lr_layers_grid" })).toBeInTheDocument();
    expect(screen.getByText("@36")).toBeInTheDocument();
    expect(screen.getByText("outer · 27,000 runs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reproduce/ })).toBeInTheDocument();
    // The Overview waits for the summary in its own panel.
    expect(screen.getByRole("tabpanel")).toBeInTheDocument();
    // The detail (per-run S3 reads) is not what the page needs.
    expect(m.experiment).not.toHaveBeenCalled();
  });

  it("looks its row up in the index when no board cached it", async () => {
    vi.mocked(fetchRunStatuses).mockResolvedValue({ [JOB]: jobRow() });
    renderRun("", false);
    expect(await screen.findByRole("tablist", { name: "Outer run" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lr_layers_grid" })).toBeInTheDocument();
    expect(screen.getByText("outer · 27,000 runs")).toBeInTheDocument();
  });

  it("lists the inner runs on the Runs tab while the summary is pending", async () => {
    renderRun("?tab=runs");
    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("trial-1")).toBeInTheDocument();
    expect(within(panel).getByText("trial-2")).toBeInTheDocument();
    expect(jobSummary).toHaveBeenCalled();
  });

  it("says how far the index has loaded on the Runs tab", async () => {
    vi.mocked(apiShell.appStatus).mockResolvedValue({
      total: 12000, counts: { created: 0, running: 0, stuck: 0, succeeded: 12000, failed: 0 },
      failed_recent: 0, rollup: null, indexing: { loaded: 12000, total: 45386 },
    });
    renderRun("?tab=runs");
    expect(await screen.findByText(/indexing 12,000 \/ 45,386 runs/)).toBeInTheDocument();
  });

  it("waits for an outer run the loading index does not hold yet instead of failing", async () => {
    vi.mocked(apiShell.appStatus).mockResolvedValue({
      total: 500, counts: { created: 0, running: 0, stuck: 0, succeeded: 500, failed: 0 },
      failed_recent: 0, rollup: null, indexing: { loaded: 500, total: 45386 },
    });
    m.experimentsPaged.mockImplementation((_ws: string, _app: string, opts: { scope?: string }) => (opts.scope
      ? Promise.reject(Object.assign(new Error(`no run '${JOB}'`), { status: 404 }))
      : Promise.resolve({ rows: [], total: 0 })));
    renderRun("?tab=runs");
    expect(await screen.findByText(/indexing 500 \/ 45,386 runs/)).toBeInTheDocument();
    expect(screen.queryByText(/no run/)).toBeNull();
  });

  it("reads the detail only for the Log tab", async () => {
    m.experiment.mockResolvedValue({
      metadata: { verstr: JOB, name: "lr_layers_grid", branch: "main", base_version: "0.0.1", timestamp: "t" },
      idx: 36, metrics: {}, series: {}, patches: {}, log_total: 1,
      log_tail: [{ timestamp: "2026-01-01T12:00:00Z", type: "note", text: "outer-note" }],
      status: { kind: "outer", children: ["k1"], tree_status: "running", command: ["python"] },
    } as unknown as ExperimentDetail);
    renderRun("?tab=log");
    expect(await screen.findByText(/outer-note/)).toBeInTheDocument();
    expect(m.experiment).toHaveBeenCalled();
  });
});
