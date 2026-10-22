/** Back to an outer run's Runs tab seen before paints its cached rows at
 *  once (marked updating), even while the revalidation never answers
 *  (production: the browser's 6 connections were all held elsewhere). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate, type NavigateFunction } from "react-router-dom";

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
import { FakeSource } from "../../../hooks/__tests__/fakeEventSource";
import type { ExperimentRow } from "../../../types";
import Run from "../../Run";
import { JOB } from "./jobFixture";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});

const jobRow = (): ExperimentRow => ({
  idx: 36, verstr: JOB, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z", note: null,
  branch: "main", base_version: "0.0.1", metrics: {}, name: "lr_layers_grid",
  status: "succeeded", tree_status: "running", kind: "outer", depth: 0, children: ["k1"],
} as ExperimentRow);

const inner = (i: number): ExperimentRow => ({
  idx: 100 + i, verstr: `0.0.2-dev.t${i}`, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z",
  note: null, branch: "main", base_version: "0.0.1", metrics: { loss: i / 10 }, name: `trial-${i}`,
  status: "succeeded", kind: "inner", depth: 1, parent: JOB,
} as ExperimentRow);

let nav: NavigateFunction;
function Nav() {
  nav = useNavigate();
  return null;
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Nav />
        <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
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
  vi.mocked(fetchRunStatuses).mockImplementation(async (_ws, _app, verstrs: string[]) => (
    verstrs[0] === JOB ? { [JOB]: jobRow() } : { [verstrs[0]]: inner(1) }));
  m.experimentsPaged.mockImplementation((_ws: string, _app: string, opts: { scope?: string }) => (
    Promise.resolve(opts.scope ? { rows: [inner(1), inner(2)], total: 2 } : { rows: [], total: 0 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("back to an outer run's Runs tab", () => {
  it("paints the cached rows at once while the list request never answers", async () => {
    renderAt(`/ws/test/app/my-app/run/${JOB}?tab=runs`);
    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("trial-1")).toBeInTheDocument();

    m.experimentsPaged.mockImplementation(never);
    await act(async () => { nav("/ws/test/app/my-app/run/0.0.2-dev.t1"); });
    expect(screen.queryByText("trial-2")).toBeNull();
    await act(async () => { nav(-1); });

    expect(screen.getByText("trial-1")).toBeInTheDocument();
    expect(screen.getByText("trial-2")).toBeInTheDocument();
    expect(screen.queryByText("loading runs…")).toBeNull();
    expect(screen.getByText("updating…")).toBeInTheDocument();
  });

  it("a filter whose answer never came paints the tab's last rows on Back, marked as updating", async () => {
    renderAt(`/ws/test/app/my-app/run/${JOB}?tab=runs`);
    expect(await screen.findByText("trial-1")).toBeInTheDocument();
    m.experimentsPaged.mockImplementation(never);
    await act(async () => { nav(`/ws/test/app/my-app/run/${JOB}?tab=runs&status=succeeded`); });
    await act(async () => { nav("/ws/test/app/my-app/run/0.0.2-dev.t1"); });
    expect(screen.queryByText("trial-2")).toBeNull();
    await act(async () => { nav(-1); });
    expect(screen.getByText("trial-2")).toBeInTheDocument();
    expect(screen.queryByText("loading runs…")).toBeNull();
    expect(screen.getByText("updating…")).toBeInTheDocument();
  });

  it("back to a run seen before paints its detail at once while its refetch never answers", async () => {
    const inner1 = "0.0.2-dev.t1";
    m.experiment.mockResolvedValue({
      metadata: { verstr: inner1, name: "trial-1", branch: "main", base_version: "0.0.1", timestamp: "t" },
      idx: 101, metrics: { loss: 0.1 }, series: {}, patches: {}, log_total: 0, log_tail: [],
      status: { kind: "inner", status: "succeeded", parent: JOB, children: [] },
    });
    renderAt(`/ws/test/app/my-app/run/${inner1}`);
    expect(await screen.findByText("changes stub")).toBeInTheDocument();

    m.experiment.mockImplementation(never);
    m.experimentsPaged.mockImplementation(never);
    await act(async () => { nav(`/ws/test/app/my-app/run/${JOB}?tab=runs`); });
    expect(screen.queryByText("changes stub")).toBeNull();
    await act(async () => { nav(-1); });
    expect(screen.getByText("changes stub")).toBeInTheDocument();
  });
});
