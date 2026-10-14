/** Plan 23 W3: a job's Runs tab is the board scoped to its subtree, with a
 *  facet sidebar, Group by inside the job (big groups open as a filter) and
 *  selection by query. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", async (orig) => {
  const actual = await orig<typeof import("../../../api")>();
  return {
    ...actual,
    api: {
      experiment: vi.fn(), experiments: vi.fn(), experimentsPaged: vi.fn(), experimentGroups: vi.fn(),
      experimentGroupRows: vi.fn(), experimentsColumns: vi.fn(), facets: vi.fn(), metricsSchema: vi.fn(),
      action: vi.fn(), actionPreview: vi.fn(), job: vi.fn(),
    },
  };
});

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../../api";
import type { GroupOpts, RunGroup } from "../../../apiGroups";
import type { ExperimentRow } from "../../../types";
import JobRuns from "../JobRuns";

const JOB = "0.0.2-rc.1";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const row = (i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow => ({
  idx: i, verstr: `0.0.2-dev.t${i}`, code_verstr: "0.0.2", timestamp: "2026-10-14T10:00:00Z", note: null,
  branch: "main", base_version: "0.0.1", params: { lr: 0.01, opt: "adam" }, metrics: { loss: i / 10 },
  status: "succeeded", depth: 1, parent: JOB, ...extra,
} as ExperimentRow);

const counts = (total: number) => ({ total, running: 0, waiting: 0, done: total, failed: 0, stuck: 0 });
const group = (key: string, total: number, rows: ExperimentRow[] = []): RunGroup => ({
  key, label: key, target: null, loose: false, counts: counts(total), aggregates: {},
  rows, rows_total: total, rows_unfiltered: total,
});
const grouped = (groups: RunGroup[]) => ({
  groups, total_groups: groups.length, total_rows: groups.reduce((n, g) => n + g.rows_total, 0),
  aggregate: "mean", running: 0,
});

function Where() {
  const { search } = useLocation();
  return <output data-testid="where">{search}</output>;
}
const url = () => new URLSearchParams(screen.getByTestId("where").textContent ?? "");

function renderRuns(search = "?tab=runs") {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
      <Routes>
        <Route
          path="/ws/:ws/app/:app/run/:verstr"
          element={<><JobRuns ws="test" app="my-app" verstr={JOB} paused={false} onPaused={() => {}} /><Where /></>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.experimentsPaged.mockResolvedValue({ rows: [row(1), row(2)], total: 312 });
  m.facets.mockResolvedValue({
    branches: ["main"], metric_keys: ["loss"], param_keys: ["lr", "opt"], tag_keys: [],
    param_values: { lr: 3, opt: 2 }, parented: 312, total: 312,
  });
  m.experimentsColumns.mockResolvedValue({ verstrs: [], idx: [], columns: {}, total: 0 });
  m.experimentGroups.mockImplementation((_ws: string, _app: string, o: GroupOpts) => {
    if (o.group === "status") return Promise.resolve(grouped([group("succeeded", 300), group("failed", 12)]));
    if (o.group === "params.lr") return Promise.resolve(grouped([group("0.01", 200, [row(1)]), group("0.1", 30, [row(2)])]));
    if (o.group === "params.opt") return Promise.resolve(grouped([group("adam", 250), group("sgd", 62)]));
    return Promise.reject(new Error(`unexpected group ${o.group}`));
  });
});

describe("the job's Runs tab", () => {
  it("lists the job's subtree: every list and facets request carries the scope", async () => {
    renderRuns();
    expect(await screen.findByText("0.0.2-dev.t1")).toBeInTheDocument();
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({ scope: JOB }));
    expect(m.facets).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({ scope: JOB }));
    for (const [, , o] of m.experimentGroups.mock.calls) expect(o.scope).toBe(JOB);
    expect(url().get("tab")).toBe("runs");
  });

  it("links each run with the tab's order and its place in it (plan 23 W7)", async () => {
    renderRuns(`?tab=runs&sort=loss&order=asc&q=${encodeURIComponent("metrics.loss < 1")}`);
    const link = await screen.findByRole("link", { name: "0.0.2-dev.t2" });
    const params = new URLSearchParams(link.getAttribute("href")!.split("?")[1]);
    expect(params.get("at")).toBe("1");
    expect(Object.fromEntries(new URLSearchParams(params.get("from")!)))
      .toEqual({ scope: JOB, q: "metrics.loss < 1", sort: "loss", order: "asc" });
  });

  it("lands filtered from a Failures tab link", async () => {
    renderRuns(`?tab=runs&q=${encodeURIComponent('failure_sig = "oom"')}`);
    await screen.findByText("0.0.2-dev.t1");
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, query: 'failure_sig = "oom"' }));
    expect(within(screen.getByRole("list", { name: "Active filters" })).getByText('failure_sig = "oom"'))
      .toBeInTheDocument();
  });

  it("shows status and param value counts, which follow the other filters", async () => {
    renderRuns(`?tab=runs&q=${encodeURIComponent("metrics.loss < 1")}&status=succeeded`);
    const side = await screen.findByRole("complementary", { name: "Facets" });
    expect(await within(side).findByRole("button", { name: 'status = "failed" (12 runs)' })).toBeInTheDocument();
    expect(await within(side).findByRole("button", { name: 'params.opt = "sgd" (62 runs)' })).toBeInTheDocument();
    const statusCall = m.experimentGroups.mock.calls.find(([, , o]) => o.group === "status")![2];
    // A facet's own filter is left out of its counts; the others apply.
    expect(statusCall).toMatchObject({ scope: JOB, query: "metrics.loss < 1" });
    expect(statusCall.status).toBeUndefined();
    const optCall = m.experimentGroups.mock.calls.find(([, , o]) => o.group === "params.opt")![2];
    expect(optCall).toMatchObject({ scope: JOB, query: "metrics.loss < 1", status: "succeeded" });
    expect(m.facets).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ scope: JOB, query: "metrics.loss < 1", status: "succeeded" }));
  });

  it("adds a clicked facet value as a filter token", async () => {
    renderRuns();
    const side = await screen.findByRole("complementary", { name: "Facets" });
    fireEvent.click(await within(side).findByRole("button", { name: 'params.opt = "sgd" (62 runs)' }));
    await waitFor(() => expect(url().get("q")).toBe('params.opt = "sgd"'));
    fireEvent.click(within(side).getByRole("button", { name: 'status = "failed" (12 runs)' }));
    await waitFor(() => expect(url().get("status")).toBe("failed"));
    expect(within(screen.getByRole("list", { name: "Active filters" })).getByText('params.opt = "sgd"'))
      .toBeInTheDocument();
  });

  it("groups inside the job, and a group over 50 runs opens as a filter", async () => {
    renderRuns("?tab=runs&group=params.lr");
    const open = await screen.findByRole("button", { name: "Filter to params.lr = 0.01 (200 runs)" });
    // A big group does not unfold: its rows are not in the table.
    expect(screen.queryByRole("button", { name: /collapse group 0\.01/i })).toBeNull();
    fireEvent.click(open);
    await waitFor(() => expect(url().get("q")).toBe("params.lr = 0.01"));
    expect(url().has("group")).toBe(false);
    expect(url().get("tab")).toBe("runs");
  });

  it("offers status and the failure signature to group by", async () => {
    renderRuns();
    fireEvent.click(await screen.findByRole("button", { name: /^group by/i }));
    expect(screen.getByRole("menuitemradio", { name: "failure_sig" })).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "status" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio", { name: "parent run" })).toBeNull();
  });

  it("selects every matching run by query and archives them after a counted confirm", async () => {
    m.actionPreview.mockResolvedValue({ count: 312, sample: [] });
    m.action.mockResolvedValue({ id: "j1", command: [], status: "running", exit_code: null, log: "" });
    renderRuns(`?tab=runs&q=${encodeURIComponent("metrics.loss < 1")}&status=succeeded`);
    await screen.findByText("0.0.2-dev.t1");
    fireEvent.click(screen.getByRole("checkbox", { name: /select all/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Select all 312 matching" }));
    expect(await screen.findByText("312 matching selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    const body = { scope: JOB, q: "metrics.loss < 1", status: "succeeded" };
    await waitFor(() => expect(m.actionPreview).toHaveBeenCalledWith("test", "my-app", "exp_archive", body));
    fireEvent.click(await screen.findByRole("button", { name: /confirm|archive 312/i, hidden: false }));
    await waitFor(() => expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_archive", body));
  });

  it("keeps the verstr list for runs picked one by one", async () => {
    m.action.mockResolvedValue({ id: "j1", command: [], status: "running", exit_code: null, log: "" });
    renderRuns();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select 0.0.2-dev.t1" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(screen.getByText("Archive 1 run?")).toBeInTheDocument();
    expect(m.actionPreview).not.toHaveBeenCalled();
  });
});
