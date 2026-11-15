/** A filter change keeps the old rows on screen, marked as updating, while
 *  its answer loads; the head never shows the old filter's count as the new
 *  one's, and the answer's first paint shows its own total. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";

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
import type { ExperimentRow } from "../../../types";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = {
  branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {},
  total: 3_053, parented: 0, jobs: 3, singles: 3_050,
};
const head = () => document.querySelector(".board-count")?.textContent ?? "";
const switcher = () => screen.getByRole("group", { name: "Experiments view" });

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const listOf = (rows: ExperimentRow[], total: number) => Object.assign([...rows], { total });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(FACETS);
  m.experimentsColumns.mockReturnValue(new Promise(() => {}));
});

describe("a filter change's board head", () => {
  it("All runs: never shows the old filter's count, then shows the answer's", async () => {
    m.experiments.mockResolvedValue(listOf([singleRow(1, { name: "solo" })], 30));
    renderExperiments("/ws/test/app/my-app?view=all");
    await screen.findByRole("link", { name: "solo" });
    expect(head()).toMatch(/\b30 runs/);
    const next = deferred<ExperimentRow[] & { total: number }>();
    m.experiments.mockReturnValue(next.promise);
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByText("updating…")).toBeInTheDocument();
    expect(head()).not.toMatch(/\b30\b/);
    await act(async () => { next.resolve(listOf([singleRow(2, { name: "ok" })], 7)); });
    expect(head()).toMatch(/\b7 runs/);
  });

  it("Single runs: neither the head nor the switch shows the old filter's count", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })], 3_050));
    renderExperiments("/ws/test/app/my-app?kind=singles&status=failed");
    await screen.findByRole("link", { name: "solo" });
    expect(head()).toMatch(/3,050 single runs/);
    const next = deferred<ReturnType<typeof jobsPage>>();
    m.experimentsPaged.mockReturnValue(next.promise);
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByText("updating…")).toBeInTheDocument();
    expect(head()).not.toMatch(/3,050/);
    expect(within(switcher()).queryByRole("button", { name: /3,050/ })).toBeNull();
    await act(async () => { next.resolve(jobsPage([singleRow(2, { name: "ok" })], 12)); });
    expect(head()).toMatch(/^12 single runs/);
  });

  it("Outer runs: neither the head nor the switch shows the old filter's count", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([topRow(1, { name: "job_a" })], 30));
    renderExperiments("/ws/test/app/my-app?status=failed");
    await screen.findByRole("link", { name: "job_a" });
    expect(head()).toMatch(/^30 outer runs/);
    const next = deferred<ReturnType<typeof jobsPage>>();
    m.experimentsPaged.mockReturnValue(next.promise);
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByText("updating…")).toBeInTheDocument();
    expect(head()).not.toMatch(/\b30\b/);
    expect(within(switcher()).queryByRole("button", { name: /\(30\)/ })).toBeNull();
    await act(async () => { next.resolve(jobsPage([topRow(2, { name: "job_b" })], 4)); });
    expect(head()).toMatch(/^4 outer runs/);
  });
});
