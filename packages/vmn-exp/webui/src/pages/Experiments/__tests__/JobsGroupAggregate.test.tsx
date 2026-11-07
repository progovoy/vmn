/** Plan 31 §2, plan 32: a grouped Outer runs header shows, in the value
 *  column (a phone's group label), the group's aggregate of its outer runs'
 *  `rolled` values (`job_aggregates`), titled by both aggregates; `— (no
 *  goal)` without a goal, `—` when none has a value. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";

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
import type { MetricAggregate } from "../../../apiGroups";
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";
import { NARROW_QUERY } from "../../../hooks/useMediaQuery";
import type { JobRolled } from "../../../types";
import { job, rolled } from "../../../util/__tests__/jobFixture";
import { notFound, renderExperiments, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const DATES: Partial<JobRolled> = {
  agg: "median", by: "field:params.trade_date", source: "own", metric: "date.best_value", goal: "max",
  value: 0.65, n: 14, of: 16, verstr: "0.0.1-dev.d7",
};
const STATS: MetricAggregate = {
  mean: 0.6, best: 0.7, median: 0.65, min: 0.5, max: 0.7, best10: 0.7, worst10: 0.5, n: 12, goal: "max",
};
const TITLE = "median of 12 outer runs' median of dates' own date.best_value";

function grouped(r: Partial<JobRolled>, aggregates: Record<string, MetricAggregate>) {
  const grid = topRow(36, { name: "lr_layers_grid", branch: "feature-x", job: job({ rolled: rolled(r) }) });
  m.experimentGroups.mockResolvedValue({
    groups: [{
      key: "feature-x", label: "branch = feature-x", target: null, loose: false,
      counts: { total: 1, running: 1, waiting: 0, done: 0, failed: 0, stuck: 0 },
      aggregates: {}, job_aggregates: aggregates, rows: [grid], rows_total: 1, rows_unfiltered: 1,
    }],
    total_groups: 1, total_rows: 1, aggregate: "median", running: 1,
  });
}

const PAGE = "/ws/test/app/my-app?view=jobs&group=branch";
const headerValue = async () => {
  await screen.findByRole("link", { name: "lr_layers_grid" });
  return document.querySelector('tr.group-row td[data-col-id="value"]') as HTMLElement;
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
});

describe("a grouped Outer runs header's value", () => {
  it("shows the group's aggregate of its outer runs' values, titled by both", async () => {
    grouped(DATES, { "date.best_value": STATS });
    renderExperiments(PAGE);
    const cell = await headerValue();
    expect(cell.textContent).toBe("median 0.65");
    expect(cell.querySelector("[title]")).toHaveAttribute("title", TITLE);
  });

  it("follows the page's aggregate, a tail with its percentile", async () => {
    grouped(DATES, { "date.best_value": STATS });
    renderExperiments(`${PAGE}&agg=best10`);
    const cell = await headerValue();
    await waitFor(() => expect(cell.textContent).toBe("best10 (p90) 0.7"));
  });

  it("marks the runs overriding the schema's summary policy", async () => {
    grouped(DATES, { "date.best_value": { ...STATS, mixed: true, policies: { min: 3 } } });
    renderExperiments(PAGE);
    const cell = await headerValue();
    expect(cell.textContent).toBe("median 0.65*");
    expect(cell.querySelector(".policy-mix-mark")).toHaveAttribute("title", "3 runs use min");
  });

  it("reads `— (no goal)` without a goal", async () => {
    grouped({ ...DATES, goal: null, value: null }, {});
    renderExperiments(PAGE);
    const cell = await headerValue();
    expect(cell.textContent).toBe("— (no goal)");
    expect(cell.querySelector("[title]")).toHaveAttribute("title", "no goal declared for date.best_value — not ranked");
  });

  it("reads `—` when none of the group's outer runs has a value", async () => {
    grouped({ ...DATES, value: null, n: 0 }, {});
    renderExperiments(PAGE);
    const cell = await headerValue();
    expect(cell.textContent).toBe("—");
    expect(cell.querySelector("[title]")).toHaveAttribute("title", "no outer run of the group has a date.best_value");
  });
});

describe("a grouped Outer runs card label's value", () => {
  beforeEach(() => fakeMedia([NARROW_QUERY]));
  afterEach(dropFakeMedia);

  it("shows the group's aggregate beside its fold", async () => {
    grouped(DATES, { "date.best_value": STATS });
    renderExperiments(PAGE);
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const label = document.querySelector(".lb-mcard-group") as HTMLElement;
    expect(label.textContent).toContain("median 0.65");
    expect(label.querySelector(`[title="${TITLE}"]`)).not.toBeNull();
  });
});
