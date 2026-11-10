/** Plan 34 §1: one row per group (`collapse_all=1`). The board asks for
 *  the headers alone, and each group reads as one row: the pooled value with
 *  its coverage (`n/of`) and the status counts summed over its attempts. Desktop
 *  and phone. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";
import { NARROW_QUERY } from "../../../hooks/useMediaQuery";
import { rolled } from "../../../util/__tests__/jobFixture";
import { notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const POOLED = {
  ...rolled({ agg: "median", by: "field:params.trade_date", source: "own", metric: "date.best_value", goal: "max" }),
  value: 0.65, n: 14, of: 16, from_earlier: 3,
  mean: 0.6, best: 0.7, median: 0.65, min: 0.5, max: 0.7,
};
const TITLE = "median of 14/16 dates' own date.best_value · 3 from earlier attempts";

function grouped() {
  const attempt = topRow(36, { name: "launch_a", tags: { launch_id: "L1" } });
  m.experimentGroups.mockImplementation((_ws: string, _app: string, opts: { collapseAll?: boolean }) => Promise.resolve({
    groups: [{
      key: "L1", label: "tags.launch_id = L1", target: null, loose: false,
      counts: { total: 3, running: 1, waiting: 0, done: 2, failed: 0, stuck: 0 },
      aggregates: {}, job_aggregates: { "date.best_value": POOLED },
      run_counts: { running: 4, waiting: 0, succeeded: 40, failed: 2, stuck: 0 },
      rows: opts.collapseAll ? [] : [attempt], rows_total: 3, rows_unfiltered: 3, clause: 'tags.launch_id = "L1"',
    }],
    total_groups: 1, total_rows: 3, aggregate: "mean", running: 1,
  }));
}

const PAGE = "/ws/test/app/my-app?view=jobs&group=tags.launch_id";
const lastOpts = () => m.experimentGroups.mock.lastCall![2];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  grouped();
});

describe("one row per group on the desktop", () => {
  it("asks for the headers alone and shows each group's pooled value, coverage and summed counts", async () => {
    renderExperiments(`${PAGE}&collapse_all=1`);
    await waitFor(() => expect(lastOpts().collapseAll).toBe(true));
    const row = await waitFor(() => {
      const found = document.querySelector("tr.group-row") as HTMLElement;
      expect(found).not.toBeNull();
      return found;
    });
    const value = row.querySelector('td[data-col-id="value"]') as HTMLElement;
    expect(value.textContent).toBe("median 0.65 14/16");
    expect(value.querySelector(`[title="${TITLE}"]`)).not.toBeNull();
    expect(row.textContent).toContain("46 runs · 4 running · 2 failed");
    expect(screen.queryByRole("link", { name: "launch_a" })).toBeNull();
    expect(screen.queryByText(/more/)).toBeNull();
  });

  it("is a toggle the URL keeps", async () => {
    renderExperiments(PAGE);
    await screen.findByRole("link", { name: "launch_a" });
    fireEvent.click(screen.getByRole("button", { name: "one row per group" }));
    expect(urlParams().get("collapse_all")).toBe("1");
    await waitFor(() => expect(screen.queryByRole("link", { name: "launch_a" })).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "one row per group" }));
    expect(urlParams().has("collapse_all")).toBe(false);
  });
});

describe("one row per group on a phone", () => {
  beforeEach(() => fakeMedia([NARROW_QUERY]));
  afterEach(dropFakeMedia);

  it("shows each group as one card with its pooled value, coverage and counts", async () => {
    renderExperiments(`${PAGE}&collapse_all=1`);
    const label = await waitFor(() => {
      const found = document.querySelector(".lb-mcard-group") as HTMLElement;
      expect(found).not.toBeNull();
      return found;
    });
    expect(label.textContent).toContain("median 0.65 14/16");
    expect(label.textContent).toContain("46 runs · 4 running · 2 failed");
    expect(label.querySelector(`[title="${TITLE}"]`)).not.toBeNull();
  });
});
