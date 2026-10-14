/** Plan 23 W2: a run with children opens the job page (header, tabs in the
 *  URL); a server without the summary endpoint keeps the single-run page. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", () => ({
  api: {
    experiment: vi.fn(), experiments: vi.fn(), metricsSchema: vi.fn(),
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
  jobFacets: vi.fn(async () => ({ metric_keys: ["val_loss"], param_keys: [], param_values: {} })),
  jobColumns: vi.fn(async () => ({ verstrs: [], idx: [], total: 0, columns: {} })),
  jobTopRuns: vi.fn(async () => []),
}));
vi.mock("../../../components/RunChanges", () => ({ default: () => <div>changes stub</div> }));

import { api } from "../../../api";
import { jobFailures, jobImportance, jobSummary } from "../../../apiJob";
import { FakeSource, lastSource } from "../../../hooks/__tests__/fakeEventSource";
import type { ExperimentDetail, RunStatus } from "../../../types";
import Run from "../../Run";
import { failuresFixture, JOB, jobSummaryFixture } from "./jobFixture";

const m = api as unknown as Record<"experiment" | "experiments" | "metricsSchema", ReturnType<typeof vi.fn>>;

function status(extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: "succeeded", exit_code: 0, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: ["python", "sweep.py"], stale_sec: null, parent: null,
    children: ["k1"], kind: "outer", depth: 0, tree_status: "running", last_metric_at: null,
    fleet: { expected: 1, counts: { running: 1 }, children: [] }, ...extra,
  };
}

const detail = (st: Partial<RunStatus> = {}): ExperimentDetail => ({
  metadata: { verstr: JOB, name: "lr_layers_grid", branch: "main", base_version: "0.0.1", timestamp: "2026-01-01T12:00:00Z" },
  idx: 36, metrics: {}, series: {}, log_tail: [{ timestamp: "2026-01-01T12:00:00Z", type: "note", text: "outer-note" }],
  log_total: 1, patches: {}, status: status(st),
} as unknown as ExperimentDetail);

function Where() {
  const { search } = useLocation();
  return <output data-testid="where">{search}</output>;
}

function renderRun(search = "") {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
      <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<><Run /><Where /></>} /></Routes>
    </MemoryRouter>,
  );
}

const notFound = () => Promise.reject(Object.assign(new Error("no children"), { status: 404 }));

beforeEach(() => {
  vi.clearAllMocks();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue([]);
  m.experiment.mockResolvedValue(detail());
  vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture());
  vi.mocked(jobFailures).mockResolvedValue(failuresFixture());
  vi.mocked(jobImportance).mockResolvedValue([]);
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("the job page", () => {
  it("opens on its header and the Overview tab", async () => {
    renderRun();
    const tabs = await screen.findByRole("tablist", { name: "Outer run" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent))
      .toEqual(["Overview", "Runs", "Charts", "Failures", "Code", "Log"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "lr_layers_grid" })).toBeInTheDocument();
    expect(screen.getByText("@36")).toBeInTheDocument();
    expect(screen.getByText("1,412/2,000")).toBeInTheDocument();
    expect(screen.getByText("41/min")).toBeInTheDocument();
    expect(screen.getByText("ETA 14m")).toBeInTheDocument();
    expect(screen.getByText(`vmn-exp list my/app --query 'parent = "${JOB}"'`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reproduce/ })).toBeInTheDocument();
    expect(screen.queryByText("Fleet")).toBeNull();
    expect(jobSummary).toHaveBeenCalledWith("test", "my-app", JOB);
  });

  it("lays the header out as title and actions, the progress, then the tabs; the CLI card last", async () => {
    vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture({
      counts: { running: 40, waiting: 546, succeeded: 1409, failed: 3, stuck: 2 },
    }));
    renderRun();
    const tabs = await screen.findByRole("tablist", { name: "Outer run" });
    expect(screen.queryByRole("link", { name: /← experiments/ })).toBeNull();
    const actions = screen.getByRole("group", { name: "Outer run actions" });
    expect(within(actions).getByRole("button", { name: /Reproduce/ })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: /Add to report/ })).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    const follows = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(actions, bar) && follows(bar, tabs)).toBe(true);
    expect(screen.getByText("3 failed")).toBeInTheDocument();
    expect(screen.getByText("2 stuck")).toBeInTheDocument();
    const cli = screen.getByText(`vmn-exp list my/app --query 'parent = "${JOB}"'`);
    expect(follows(screen.getByRole("tabpanel"), cli)).toBe(true);
  });

  it("keeps the tab in the URL and moves with the arrow keys", async () => {
    renderRun("?tab=failures");
    expect(await screen.findByRole("tab", { name: "Failures" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("CUDA out of memory")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.getByTestId("where").textContent).toBe("?tab=runs");
    // The Runs tab is the job's own board (plan 23 W3).
    expect(within(screen.getByRole("tabpanel")).getByRole("complementary", { name: "Facets" })).toBeInTheDocument();
    expect(await within(screen.getByRole("tabpanel")).findByRole("grid", { name: "experiments" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Runs" }), { key: "ArrowRight" });
    expect(screen.getByTestId("where").textContent).toBe("?tab=charts");
    expect(await within(screen.getByRole("tabpanel")).findByRole("group", { name: "Chart" })).toBeInTheDocument();
  });

  it("keeps the job's own Changes and log under Code and Log", async () => {
    renderRun("?tab=code");
    expect(await screen.findByText("changes stub")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Log" }));
    expect(await screen.findByText(/outer-note/)).toBeInTheDocument();
  });

  it("falls back to the single-run page when the server has no summary (404)", async () => {
    vi.mocked(jobSummary).mockImplementation(notFound);
    renderRun();
    await waitFor(() => expect(screen.getByText("Fleet")).toBeInTheDocument());
    expect(screen.queryByRole("tablist", { name: "Outer run" })).toBeNull();
  });

  it("never asks a single run for a summary", async () => {
    m.experiment.mockResolvedValue(detail({ kind: "single", children: [], fleet: null, tree_status: null }));
    renderRun();
    await screen.findByRole("heading", { name: "lr_layers_grid" });
    expect(jobSummary).not.toHaveBeenCalled();
  });

  it("gives an inner run's page its job context bar (plan 23 W7)", async () => {
    m.experiment.mockResolvedValue(detail({ kind: "inner", children: [], fleet: null, tree_status: null, parent: JOB }));
    renderRun();
    const bar = await screen.findByRole("navigation", { name: "Outer run context" });
    expect(await within(bar).findByRole("link", { name: "lr_layers_grid" })).toBeInTheDocument();
    expect(jobSummary).toHaveBeenCalledWith("test", "my-app", JOB);
  });

  it("follows the job's subtree live and refreshes its summary on a change", async () => {
    renderRun();
    await screen.findByRole("tablist", { name: "Outer run" });
    await waitFor(() => expect(lastSource().url).toBe(`/api/v1/workspaces/test/apps/my-app/events?scope=${JOB}`));
    act(() => lastSource().open());
    expect(screen.getByText(/live · updated/)).toBeInTheDocument();
    const before = vi.mocked(jobSummary).mock.calls.length;
    act(() => lastSource().emit("change", { generation: "2", changed: { rows: 3 } }));
    await waitFor(() => expect(vi.mocked(jobSummary).mock.calls.length).toBeGreaterThan(before));
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByText(/paused · updated/)).toBeInTheDocument();
  });
});
