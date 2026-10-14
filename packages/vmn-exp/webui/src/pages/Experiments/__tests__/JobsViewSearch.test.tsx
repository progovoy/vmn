/** Plan 23 W11 (§3.5): a search in the Jobs view covers every run. Jobs with
 *  matching runs stay listed with a `N matching runs` chip opening their Runs
 *  tab, and a result line switches to All runs with the filter kept. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
import { location, notFound, renderExperiments, singleRow, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(36, { name: "lr_layers_grid", matched: 412 });
const SOLO = singleRow(12, { name: "solo", matched: 1 });
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];
const SEARCHED = "/ws/test/app/my-app?search=grid";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue({ rows: [GRID, SOLO], total: 2, jobs_matched: 2, runs_matched: 413 });
});

describe("Jobs view search", () => {
  it("asks the server to match every run's subtree when there is text", async () => {
    renderExperiments(SEARCHED);
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastOpts()).toMatchObject({ top: true, matchSubtree: true });
  });

  it("does not match subtrees without text or a query", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastOpts().matchSubtree).toBeFalsy();
  });

  it("shows the result line and switches to All runs keeping the filter", async () => {
    renderExperiments(SEARCHED);
    expect(await screen.findByText("2 jobs · 413 runs match")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "show all 413 runs" }));
    await waitFor(() => expect(urlParams().get("view")).toBe("all"));
    expect(urlParams().get("search")).toBe("grid");
  });

  it("puts a chip on a job opening its Runs tab with the search", async () => {
    renderExperiments(SEARCHED);
    const chip = await screen.findByRole("link", { name: "412 matching runs" });
    const href = new URL(chip.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe(`/ws/test/app/my-app/run/${encodeURIComponent(GRID.verstr)}`);
    expect([href.searchParams.get("tab"), href.searchParams.get("search")]).toEqual(["runs", "grid"]);
  });

  it("keeps single runs that match as plain rows, without a chip", async () => {
    renderExperiments(SEARCHED);
    await screen.findByRole("link", { name: "solo" });
    expect(screen.queryByRole("link", { name: /^1 matching run/ })).toBeNull();
  });

  it("shows no result line without a search", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(screen.queryByText(/runs? match/)).toBeNull();
    expect(location.pathname).toBe("/ws/test/app/my-app");
  });
});
