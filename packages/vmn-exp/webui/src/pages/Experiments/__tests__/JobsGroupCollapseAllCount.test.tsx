/** Plan 34 §1: one row per group (`collapse_all=1`) shows groups, so the
 *  board's count names them beside the outer runs they hold:
 *  `14 groups · 44 outer runs`. */
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
import { notFound, renderExperiments } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 9_000 };

const header = (i: number) => ({
  key: `L${i}`, label: `tags.launch_id = L${i}`, target: null, loose: false,
  counts: { total: 3, running: 0, waiting: 0, done: 3, failed: 0, stuck: 0 },
  aggregates: {}, job_aggregates: {}, run_counts: { succeeded: 30 },
  rows: [], rows_total: 3, rows_unfiltered: 3, clause: `tags.launch_id = "L${i}"`,
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue({ ...FACETS, parented: 8_000, jobs: 44, singles: 950 });
  m.experimentGroups.mockResolvedValue({
    groups: Array.from({ length: 14 }, (_, i) => header(i)),
    total_groups: 14, total_rows: 44, aggregate: "mean", running: 0,
  });
});

describe("the count of a board of one row per group", () => {
  it("names the groups and the outer runs they hold", async () => {
    renderExperiments("/ws/test/app/my-app?group=tags.launch_id&collapse_all=1");
    expect(await screen.findByText(/^14 groups · 44 outer runs/)).toBeInTheDocument();
  });

  it("stays the outer runs' count with the groups open", async () => {
    renderExperiments("/ws/test/app/my-app?group=tags.launch_id");
    expect(await screen.findByText(/^44 outer runs/)).toBeInTheDocument();
  });
});
