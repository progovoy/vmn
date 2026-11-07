/** Plan 32 F10: the Jobs view's Best column is of the server's `main`
 *  metric (the page's, with its goal), never one the web picks from the
 *  rows or the schema. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

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
import { notFound, renderExperiments, singleRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const SOLO = singleRow(12, { name: "solo", metrics: { val_loss: 0.4, acc: 0.9 } });
const bestOf = (name: string) =>
  screen.getByRole("link", { name }).closest("tr")!.querySelector('[data-col-id="value"]')!;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  // The schema declares val_loss first: the server's main is acc all the same.
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" }, acc: { goal: "max" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
});

describe("the Jobs view's main metric", () => {
  it("is the page's main, with its goal, on a page of single runs only", async () => {
    m.experimentsPaged.mockResolvedValue({ rows: [SOLO], total: 1, main: { metric: "acc", goal: "max" } });
    renderExperiments();
    await screen.findByRole("link", { name: "solo" });
    expect(bestOf("solo").textContent).toBe("0.9 ↑");
  });

  it("is none when the page names none: no value from the schema's first goal", async () => {
    m.experimentsPaged.mockResolvedValue({ rows: [SOLO], total: 1 });
    renderExperiments();
    await screen.findByRole("link", { name: "solo" });
    expect(bestOf("solo").textContent).toBe("");
  });

  it("is the grouped page's main", async () => {
    m.experimentGroups.mockResolvedValue({
      groups: [{
        key: "main", label: "branch = main", target: null, loose: false,
        counts: { total: 1, running: 0, waiting: 0, done: 1, failed: 0, stuck: 0 },
        aggregates: {}, rows: [SOLO], rows_total: 1, rows_unfiltered: 1,
      }],
      total_groups: 1, total_rows: 1, aggregate: "mean", running: 0,
      metric: null, goal: null, main: { metric: "acc", goal: "max" },
    });
    renderExperiments("/ws/test/app/my-app?group=branch");
    await screen.findByRole("link", { name: "solo" });
    expect(bestOf("solo").textContent).toBe("0.9 ↑");
  });
});
