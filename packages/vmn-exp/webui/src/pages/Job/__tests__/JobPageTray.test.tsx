/** The app-wide selection tray on a job page and an inner run's page: the
 *  picks made on the Jobs view or another job stay in view. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", () => ({
  api: {
    experiment: vi.fn(), experiments: vi.fn(), metricsSchema: vi.fn(), experimentsColumns: vi.fn(),
    experimentsPaged: vi.fn(() => Promise.resolve({ rows: [], total: 0 })),
    facets: vi.fn(() => Promise.reject(new Error("no facets"))),
    experimentGroups: vi.fn(() => Promise.reject(new Error("no groups"))),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));
vi.mock("../../../components/TrainingCurves", () => ({ default: () => null }));
vi.mock("../../../apiJobCharts", () => ({
  jobFacets: vi.fn(async () => ({ metric_keys: [], param_keys: [], param_values: {} })),
  jobColumns: vi.fn(async () => ({ verstrs: [], idx: [], total: 0, columns: {} })),
  jobTopRuns: vi.fn(async () => []),
}));
vi.mock("../../../components/RunChanges", () => ({ default: () => null }));

import { api } from "../../../api";
import { jobSummary } from "../../../apiJob";
import { FakeSource } from "../../../hooks/__tests__/fakeEventSource";
import type { ExperimentDetail } from "../../../types";
import { writePicks } from "../../../util/runSelection";
import Run from "../../Run";
import { WithTray } from "../../__tests__/withTray";
import { JOB, jobSummaryFixture } from "./jobFixture";

const m = api as unknown as Record<"experiment" | "experiments" | "metricsSchema", ReturnType<typeof vi.fn>>;

const jobDetail = {
  metadata: { verstr: JOB, name: "grid", branch: "main", base_version: "0.0.1", timestamp: "2026-01-01T12:00:00Z" },
  idx: 36, metrics: {}, series: {}, log_tail: [], log_total: 0, patches: {},
  status: {
    status: "succeeded", exit_code: 0, command: ["python"], parent: null, children: ["k1"], kind: "outer",
    depth: 0, tree_status: "succeeded", fleet: { expected: 1, counts: {}, children: [] },
  },
} as unknown as ExperimentDetail;

function renderRun(path: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<WithTray><Run /></WithTray>} /></Routes>
    </MemoryRouter>,
  );
}

const trays = () => screen.queryAllByRole("region", { name: "Selection" });

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue([]);
  m.experiment.mockResolvedValue(jobDetail);
  vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture());
  writePicks("test", "my-app", [{ verstr: "a", job: "J1" }, { verstr: "b", job: "J2" }]);
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("the selection tray on a job page", () => {
  it("shows the app's picks on the Overview tab", async () => {
    renderRun(`/ws/test/app/my-app/run/${JOB}`);
    await screen.findByRole("tab", { name: /overview/i });
    expect(trays()).toHaveLength(1);
    expect(within(trays()[0]).getByRole("status")).toHaveTextContent("2 selected from 2 outer runs");
  });

  it("shows one tray, the board's, on the Runs tab", async () => {
    renderRun(`/ws/test/app/my-app/run/${JOB}?tab=runs`);
    await screen.findByRole("tab", { name: /runs/i });
    await screen.findByRole("region", { name: "Selection" });
    expect(trays()).toHaveLength(1);
  });

  it("stays when Escape is pressed off a board", async () => {
    renderRun(`/ws/test/app/my-app/run/${JOB}`);
    await screen.findByRole("tab", { name: /overview/i });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(trays()).toHaveLength(1);
  });
});

describe("the selection tray on an inner run's page", () => {
  it("shows the app's picks", async () => {
    m.experiment.mockResolvedValue({
      ...jobDetail,
      metadata: { ...jobDetail.metadata, verstr: "k1", name: "trial" },
      status: { ...jobDetail.status, kind: "inner", children: [], fleet: null, parent: JOB, depth: 1 },
    });
    renderRun("/ws/test/app/my-app/run/k1");
    expect(within(await screen.findByRole("region", { name: "Selection" })).getByRole("status"))
      .toHaveTextContent("2 selected from 2 outer runs");
  });
});
