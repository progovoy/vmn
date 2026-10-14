/** A group too big to unfold opens as a filter (plan 23 W10, §3.4): in the
 *  Jobs view and in All runs, a group over 50 runs is a header whose
 *  button adds its clause as a filter token and drops group=; Back
 *  restores the grouped view. Smaller groups keep their fold and +N more. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../components/ParamPlots", () => ({ default: () => null }));
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
import type { ExperimentRow } from "../../../types";
import { jobsPage, nav, notFound, renderExperiments, singleRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = {
  branches: ["main", "dev"], metric_keys: [], param_keys: ["lr"], tag_keys: [], param_values: { lr: 3 },
  total: 4000, parented: 0,
};
const counts = (total: number) => ({ total, running: 0, waiting: 0, done: total, failed: 0, stuck: 0 });
const group = (key: string, label: string, rows: ExperimentRow[], total: number, extra = {}) => ({
  key, label, target: null, loose: false, counts: counts(total), aggregates: {},
  rows, rows_total: total, rows_unfiltered: total, ...extra,
});
const SMALL = singleRow(1, { name: "small_one", branch: "dev" });
const BIG = singleRow(2, { name: "big_one" });
const groups = (gs: ReturnType<typeof group>[]) => ({
  groups: gs, total_groups: gs.length, total_rows: 3020, aggregate: "mean", running: 0,
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.experimentsColumns.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(FACETS);
  m.experimentsPaged.mockResolvedValue(jobsPage([BIG, SMALL]));
  m.experiments.mockResolvedValue(Object.assign([BIG, SMALL], { total: 2 }));
  m.experimentGroups.mockResolvedValue(groups([
    group("main", "branch = main", [BIG], 3000),
    group("dev", "branch = dev", [SMALL], 20),
  ]));
});

describe("the Jobs view, grouped", () => {
  it("a group over 50 runs is a Filter to button, not a fold", async () => {
    renderExperiments("/ws/test/app/my-app?group=branch");
    const open = await screen.findByRole("button", { name: 'Filter to branch = "main" (3,000 runs)' });
    expect(screen.queryByRole("link", { name: "big_one" })).toBeNull();
    expect(screen.queryByRole("button", { name: /expand group branch = main/i })).toBeNull();
    // A small group still unfolds in place, with its +N more.
    expect(screen.getByRole("link", { name: "small_one" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /19 more/ })).toBeInTheDocument();
    fireEvent.click(open);
    await waitFor(() => expect(urlParams().has("group")).toBe(false));
    expect(within(screen.getByRole("list", { name: "Active filters" })).getByText(/main/)).toBeInTheDocument();
    act(() => nav.back());
    await waitFor(() => expect(urlParams().get("group")).toBe("branch"));
  });

  it("prefers the server's clause", async () => {
    m.experimentGroups.mockResolvedValue(groups([
      group("0.01", "params.lr = 0.01", [BIG], 200, { clause: "params.lr = 0.01" }),
    ]));
    renderExperiments("/ws/test/app/my-app?group=params.lr");
    fireEvent.click(await screen.findByRole("button", { name: "Filter to params.lr = 0.01 (200 runs)" }));
    await waitFor(() => expect(urlParams().get("q")).toBe("params.lr = 0.01"));
    expect(urlParams().has("group")).toBe(false);
  });

  it("counts a group of jobs in jobs", async () => {
    m.facets.mockResolvedValue({ ...FACETS, parented: 9000, jobs: 80, singles: 3000 });
    m.experimentGroups.mockResolvedValue(groups([group("main", "branch = main", [BIG], 60)]));
    renderExperiments("/ws/test/app/my-app?group=branch");
    expect(await screen.findByRole("button", { name: 'Filter to branch = "main" (60 jobs)' })).toBeInTheDocument();
  });
});

describe("All runs, grouped", () => {
  it("a group over 50 runs opens as a filter; Back restores the grouping", async () => {
    m.experimentGroups.mockResolvedValue(groups([
      group("0.01", "params.lr = 0.01", [BIG], 200),
      group("0.1", "params.lr = 0.1", [SMALL], 20),
    ]));
    renderExperiments("/ws/test/app/my-app?view=all&group=params.lr");
    const open = await screen.findByRole("button", { name: "Filter to params.lr = 0.01 (200 runs)" });
    expect(screen.getByRole("link", { name: "small_one" })).toBeInTheDocument();
    fireEvent.click(open);
    await waitFor(() => expect(urlParams().get("q")).toBe("params.lr = 0.01"));
    expect(urlParams().has("group")).toBe(false);
    expect(urlParams().get("view")).toBe("all");
    act(() => nav.back());
    await waitFor(() => expect(urlParams().get("group")).toBe("params.lr"));
    expect(urlParams().has("q")).toBe(false);
  });
});
