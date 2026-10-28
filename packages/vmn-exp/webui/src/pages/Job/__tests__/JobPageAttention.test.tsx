/** Plan 28 P1 on an outer run's page: the attention strip over its subtree
 *  (`experiments-status?scope=`), its parts opening the Runs tab filtered. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

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
import type { AppStatus } from "../../../shell/contracts";
import Run from "../../Run";
import { JOB } from "./jobFixture";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});
const counts = (stuck: number, running: number) => ({ created: 0, running, stuck, succeeded: 5, failed: 2 });
const SCOPED: AppStatus = {
  total: 30, failed_recent: 2, rollup: "stuck", counts: counts(4, 1),
  attention: [{ key: "unstable", label: "unstable", level: "warn", count: 3, q: 'tags.health = "unstable"' }],
};
const APP: AppStatus = { total: 900, failed_recent: 50, rollup: "stuck", counts: counts(70, 9) };

const location = { search: "" };
function Probe() {
  location.search = useLocation().search;
  return null;
}
const urlParams = () => new URLSearchParams(location.search);
const linkParams = (name: string) =>
  new URLSearchParams(screen.getByRole("link", { name }).getAttribute("href")!.split("?")[1]);

function renderRun(search = "") {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}${search}`]}>
        <Probe />
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
  vi.mocked(apiShell.appStatus).mockImplementation((_ws, _tag, scope?: string) =>
    Promise.resolve(scope === JOB ? SCOPED : APP));
  vi.mocked(fetchRunStatuses).mockResolvedValue({
    [JOB]: { idx: 36, verstr: JOB, name: "grid", kind: "outer", depth: 0, children: ["k"], status: "running", metrics: {} },
  } as never);
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("the attention strip on an outer run's page", () => {
  it("counts the run's subtree, not the app", async () => {
    renderRun();
    const strip = (await screen.findByRole("link", { name: "4 stuck" })).closest('[role="status"]')!;
    expect(strip).toHaveTextContent("4 stuck · 2 failed in 24h · 3 unstable · 1 running");
    expect(apiShell.appStatus).toHaveBeenCalledWith("test", "my-app", JOB);
  });

  it("links each part to the Runs tab filtered", async () => {
    renderRun("?tab=overview");
    await screen.findByRole("link", { name: "4 stuck" });
    expect(linkParams("4 stuck").get("tab")).toBe("runs");
    expect(linkParams("4 stuck").get("status")).toBe("stuck");
    const failed = linkParams("2 failed in 24h");
    expect([failed.get("tab"), failed.get("status")]).toEqual(["runs", "failed"]);
    expect(failed.get("q")).toMatch(/^finished_at >= "/);
    const unstable = linkParams("3 unstable");
    expect([unstable.get("tab"), unstable.get("q")]).toEqual(["runs", 'tags.health = "unstable"']);
    expect(screen.getByRole("link", { name: "4 stuck" }).getAttribute("href"))
      .toMatch(new RegExp(`^/ws/test/app/my-app/run/${encodeURIComponent(JOB).replace(/[.+]/g, "\\$&")}\\?`));
  });

  it("sets the Runs tab's filter bar when followed there", async () => {
    renderRun("?tab=runs&q=metrics.loss%20%3C%201");
    fireEvent.click(await screen.findByRole("link", { name: "3 unstable" }));
    await waitFor(() => expect(urlParams().get("q")).toBe('tags.health = "unstable"'));
    const bar = await screen.findByRole("list", { name: "Active filters" });
    await waitFor(() => expect(within(bar).queryAllByRole("listitem").map((li) => li.getAttribute("data-token")))
      .toEqual(['tags.health = "unstable"']));
  });
});
