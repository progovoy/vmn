/** The Jobs view's Group by (plan 23 §3.4): the view is grouped by parent
 *  run, so the menu says so; "none" opens All runs flat. */
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
import { jobsPage, notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(36, { name: "lr_layers_grid", branch: "feature-x" });
const trigger = () => screen.getByRole("button", { name: /^Group by/ });
const parentItem = () => screen.getByRole("menuitemradio", { name: /^parent run/ });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID]));
});

describe("the Jobs view's Group by", () => {
  it("shows parent run as the view's grouping, none unchecked", async () => {
    renderExperiments("/ws/test/app/my-app?view=jobs");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(trigger().textContent).toMatch(/parent run/);
    fireEvent.click(trigger());
    expect(parentItem()).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "none" })).toHaveAttribute("aria-checked", "false");
    // The view's own grouping has no groups to sort or sum up.
    expect(screen.queryByRole("group", { name: "Aggregate" })).toBeNull();
  });

  it("picking none opens All runs flat, the filters kept", async () => {
    renderExperiments("/ws/test/app/my-app?view=jobs&q=params.lr%20%3E%201");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(trigger());
    fireEvent.click(screen.getByRole("menuitemradio", { name: "none" }));
    await waitFor(() => expect(urlParams().get("view")).toBe("all"));
    expect(urlParams().get("group")).toBeNull();
    expect(urlParams().get("q")).toBe("params.lr > 1");
  });

  it("grouped by a field, parent run brings the jobs back ungrouped", async () => {
    m.experimentGroups.mockResolvedValue({
      groups: [{
        key: "feature-x", label: "branch = feature-x", target: null, loose: false,
        counts: { total: 1, running: 1, waiting: 0, done: 0, failed: 0, stuck: 0 },
        aggregates: {}, rows: [GRID], rows_total: 1, rows_unfiltered: 1,
      }],
      total_groups: 1, total_rows: 1, aggregate: "mean", running: 1,
    });
    renderExperiments("/ws/test/app/my-app?view=jobs&group=branch");
    await waitFor(() => expect(trigger().textContent).toMatch(/branch/));
    fireEvent.click(trigger());
    expect(parentItem()).toHaveAttribute("aria-checked", "false");
    fireEvent.click(parentItem());
    await waitFor(() => expect(urlParams().get("group")).toBeNull());
    expect(urlParams().get("view")).toBe("jobs");
  });
});
