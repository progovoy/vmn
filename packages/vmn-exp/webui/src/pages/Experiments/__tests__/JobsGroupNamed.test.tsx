/** Plan 34 follow-ups, one row per group (`collapse_all=1`): with no unit
 *  valued in any group there are no rows to name the aggregate, so the page's
 *  `job_agg` does, and each header reads `—` or `— (no goal)`, never blank
 *  (plan 32 §0). A header's summed counts add its outer runs' lost runs as
 *  the rows do (`· 1 lost`, plan 34 §3). Desktop and phone. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { waitFor } from "@testing-library/react";

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
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";
import { NARROW_QUERY } from "../../../hooks/useMediaQuery";
import { renderExperiments, notFound } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const CHOICE = {
  agg: "median", by: "field:params.trade_date", source: "own", metric: "date.best_value", goal: "max", percentile: null,
};

function grouped(choice: Record<string, unknown>, lost = 0) {
  m.experimentGroups.mockResolvedValue({
    groups: [{
      key: "L1", label: "tags.launch_id = L1", target: null, loose: false,
      counts: { total: 3, running: 1, waiting: 0, done: 2, failed: 0, stuck: 0 },
      aggregates: {}, job_aggregates: {},
      run_counts: { running: 4, waiting: 0, succeeded: 40, failed: 2, stuck: 0 }, lost,
      rows: [], rows_total: 3, rows_unfiltered: 3, clause: 'tags.launch_id = "L1"',
    }],
    total_groups: 1, total_rows: 3, aggregate: "mean", running: 1, job_agg: choice,
  });
}

const PAGE = "/ws/test/app/my-app?view=jobs&group=tags.launch_id&collapse_all=1";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
});

const valueCell = () => waitFor(() => {
  const found = document.querySelector('tr.group-row td[data-col-id="value"]') as HTMLElement;
  expect(found?.textContent).toBeTruthy();
  return found;
});

describe("a header with no valued unit, on the desktop", () => {
  it("reads `—`, titled by the page's aggregate", async () => {
    grouped(CHOICE);
    renderExperiments(PAGE);
    const cell = await valueCell();
    expect(cell.textContent).toBe("—");
    expect(cell.querySelector('[title="no outer run of the group has a date.best_value"]')).not.toBeNull();
  });

  it("reads `— (no goal)` for a metric without a goal", async () => {
    grouped({ ...CHOICE, goal: null });
    renderExperiments(PAGE);
    expect((await valueCell()).textContent).toBe("— (no goal)");
  });

  it("adds the outer runs' lost runs to the summed counts", async () => {
    grouped(CHOICE, 1);
    renderExperiments(PAGE);
    const row = (await valueCell()).closest("tr") as HTMLElement;
    expect(row.textContent).toContain("46 runs · 4 running · 2 failed · 1 lost");
  });
});

describe("a header with no valued unit, on a phone", () => {
  beforeEach(() => fakeMedia([NARROW_QUERY]));
  afterEach(dropFakeMedia);

  it("reads `—` and the lost runs beside the counts", async () => {
    grouped(CHOICE, 2);
    renderExperiments(PAGE);
    const label = await waitFor(() => {
      const found = document.querySelector(".lb-mcard-group") as HTMLElement;
      expect(found?.textContent).toContain("—");
      return found;
    });
    expect(label.textContent).toContain("46 runs · 4 running · 2 failed · 2 lost");
  });
});
