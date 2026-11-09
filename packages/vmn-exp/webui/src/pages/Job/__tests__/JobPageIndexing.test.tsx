/** An outer run's page over answers still indexing (plan 33 §2.2) says
 *  "indexing N% — results incomplete" from the answers themselves (the
 *  summary, the Runs tab's list), whatever the status poll says. */
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
import { jobFailures, jobSummary } from "../../../apiJob";
import { apiShell } from "../../../apiShell";
import { fetchRunStatuses } from "../../../apiSeries";
import { createQueryClient } from "../../../queryClient";
import { FakeSource } from "../../../hooks/__tests__/fakeEventSource";
import type { ExperimentRow } from "../../../types";
import Run from "../../Run";
import { failuresFixture, JOB, jobSummaryFixture } from "./jobFixture";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});
const INDEXING = { loaded: 120_000, total: 734_000 };
const INCOMPLETE = "indexing 16% — results incomplete";

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

function renderRun(search: string) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
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
  vi.mocked(jobFailures).mockResolvedValue(failuresFixture());
  vi.mocked(apiShell.appStatus).mockImplementation(never);
  vi.mocked(fetchRunStatuses).mockResolvedValue({ [JOB]: jobRow() });
  m.experimentsPaged.mockResolvedValue({ rows: [inner(1)], total: 1 });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("an outer run's page over answers still indexing", () => {
  it("says the Runs tab's list is incomplete from its own answer", async () => {
    m.experimentsPaged.mockResolvedValue({ rows: [inner(1)], total: 1, indexing: INDEXING });
    renderRun("?tab=runs&layout=flat");
    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText(new RegExp(INCOMPLETE))).toBeInTheDocument();
  });

  it("says the summary is incomplete from its own answer", async () => {
    vi.mocked(jobSummary).mockResolvedValue({ ...jobSummaryFixture(), indexing: INDEXING });
    renderRun("?tab=overview");
    expect(await screen.findByText(INCOMPLETE)).toBeInTheDocument();
  });

  it("says nothing of a summary over a loaded index", async () => {
    vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture());
    renderRun("?tab=overview");
    expect(await screen.findByRole("list", { name: "Outer run KPIs" })).toBeInTheDocument();
    expect(screen.queryByText(/results incomplete/)).toBeNull();
  });
});
