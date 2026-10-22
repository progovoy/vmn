/** The Single runs view lists runs, not outer runs: the All runs board's
 *  default columns (status, experiment, goal metrics, varying params, when),
 *  never an outer run's progress/best/spread/rate. And the other top views'
 *  first pages are prefetched, so switching to one paints at once. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getTotalSize: () => count * estimateSize(),
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * estimateSize(), size: estimateSize(), end: (index + 1) * estimateSize(),
      })),
  }),
}));

import { api } from "../../../api";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";
import { PREFETCH_DELAY_MS } from "../useViewPrefetch";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = {
  branches: ["main"], metric_keys: ["loss"], param_keys: ["lr"], tag_keys: [], param_values: {},
  total: 3_053, parented: 50, jobs: 3, singles: 3_050,
};
const SINGLES = [
  singleRow(2, { name: "solo_b", metrics: { loss: 0.2 }, params: { lr: 0.01 } }),
  singleRow(1, { name: "solo_a", metrics: { loss: 0.3 }, params: { lr: 0.1 } }),
];
const JOBS = [topRow(3, { name: "job_a" })];
const never = () => new Promise<never>(() => {});
const headers = () => screen.getAllByRole("columnheader").map((th) => th.textContent?.trim() ?? "");
const switcher = () => screen.getByRole("group", { name: "Experiments view" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.config.mockRejectedValue(notFound());
  m.experimentsColumns.mockImplementation(never);
  m.facets.mockResolvedValue(FACETS);
  m.experimentsPaged.mockImplementation((_ws: string, _app: string, o: { top?: unknown }) =>
    Promise.resolve(jobsPage(o.top === "singles" ? SINGLES : JOBS, o.top === "singles" ? 3_050 : 3)));
  m.experiments.mockResolvedValue(Object.assign([...SINGLES], { total: 2 }));
});

describe("the Single runs view", () => {
  it("shows the runs board's columns, not an outer run's", async () => {
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await screen.findByRole("link", { name: "solo_a" });
    const shown = headers();
    for (const job of ["outer run · progress", "best", "spread", "rate", "ETA"]) {
      expect(shown.some((h) => h.startsWith(job))).toBe(false);
    }
    expect(shown.some((h) => h.startsWith("loss"))).toBe(true);
    expect(shown.some((h) => h.startsWith("lr"))).toBe(true);
    expect(shown.some((h) => h.startsWith("when"))).toBe(true);
    expect(screen.getByText("3,050 single runs")).toBeInTheDocument();
  });

  it("asks for the single runs, newest first", async () => {
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await screen.findByRole("link", { name: "solo_a" });
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({
      top: "singles", sort: "idx", offset: 0,
    }));
    const order = screen.getAllByRole("link", { name: /^solo_/ }).map((a) => a.textContent);
    expect(order).toEqual(["solo_b", "solo_a"]);
  });
});

describe("switching views", () => {
  it("prefetches the other views' first pages under the current filters", async () => {
    renderExperiments("/ws/test/app/my-app?status=succeeded");
    await screen.findByRole("link", { name: "job_a" });
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({
      top: "singles", status: "succeeded", sort: "idx",
    })), { timeout: PREFETCH_DELAY_MS + 2_000 });
    await waitFor(() => expect(m.experiments).toHaveBeenCalledWith("test", "my-app", "idx", "succeeded"));
  });

  it("Single runs paints the prefetched rows with no new request", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "job_a" });
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app",
      expect.objectContaining({ top: "singles" })), { timeout: PREFETCH_DELAY_MS + 2_000 });
    await new Promise((r) => setTimeout(r, 0));
    const calls = m.experimentsPaged.mock.calls.length;
    m.experimentsPaged.mockImplementation(never);
    fireEvent.click(within(switcher()).getByRole("button", { name: /^Single runs/ }));
    expect(await screen.findByRole("link", { name: "solo_a" })).toBeInTheDocument();
    expect(screen.queryByText(/^loading/)).toBeNull();
    expect(screen.queryByText("updating…")).toBeNull();
    expect(m.experimentsPaged.mock.calls.length).toBe(calls);
  });
});
