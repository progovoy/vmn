/** Plan 22 F3, F4: the grouped board takes the effective aggregate and the
 *  running count from the grouped payload's top level, not from its own
 *  conf read or the rows it happens to hold. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(),
    experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const facets = { branches: ["main"], metric_keys: ["loss"], param_keys: [], tag_keys: [], param_values: {}, parented: 0, total: 3 };
const agg = { mean: 0.3, best: 0.1, median: 0.25, min: 0.1, max: 0.5, n: 2 };

/** One `branch = main` group of two finished rows; a third run (running)
 *  sits in a group past the loaded page. */
function payload(extra: Record<string, unknown> = {}) {
  return {
    groups: [{
      key: "main", label: "branch = main", target: null, aggregates: { loss: agg },
      rows: [row(1, { metrics: { loss: 0.1 } }), row(2, { metrics: { loss: 0.5 } })], rows_total: 2,
      counts: { total: 2, running: 0, waiting: 0, done: 2, failed: 0, stuck: 0 },
    }],
    total_groups: 2, total_rows: 3, aggregate: "median", running: 1, ...extra,
  };
}

const groupBy = () => screen.findByRole("button", { name: /^group by/i });
const aggChoice = (name: string) =>
  within(screen.getByRole("group", { name: "Aggregate" })).getByRole("menuitemradio", { name });
const tag = () => document.querySelector('thead th[data-col-id="m:loss"] .agg-tag')?.textContent;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue(page([row(1), row(2)]));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockResolvedValue({ conf: { experiment: { ui: { group_aggregate: "max" } } }, text: "" });
  m.facets.mockResolvedValue(facets);
  m.experimentGroups.mockResolvedValue(payload());
});
afterEach(() => { vi.useRealTimers(); });

describe("the effective aggregate comes from the server (plan 22 F3)", () => {
  it("tags the columns and checks the menu with the payload's aggregate when the URL has no agg=", async () => {
    renderBoard("/ws/test/app/my-app?group=branch");
    await waitFor(() => expect(tag()).toBe("median"));
    expect(m.experimentGroups.mock.calls[0][2].agg).toBeUndefined();
    fireEvent.click(await groupBy());
    expect(aggChoice("median")).toHaveAttribute("aria-checked", "true");
    expect(aggChoice("max")).toHaveAttribute("aria-checked", "false");
    // The board no longer reads the app's conf for it.
    expect(m.config).not.toHaveBeenCalled();
  });

  it("shows the URL's agg= over the server's default", async () => {
    m.experimentGroups.mockResolvedValue(payload({ aggregate: "best" }));
    renderBoard("/ws/test/app/my-app?group=branch&agg=best");
    await waitFor(() => expect(tag()).toBe("best"));
    fireEvent.click(await groupBy());
    expect(aggChoice("best")).toHaveAttribute("aria-checked", "true");
  });

  it("writes agg= away from the server's default, and drops it on picking the default back", async () => {
    renderBoard("/ws/test/app/my-app?group=branch");
    await waitFor(() => expect(tag()).toBe("median"));
    m.experimentGroups.mockResolvedValue(payload({ aggregate: "min" }));
    fireEvent.click(await groupBy());
    fireEvent.click(aggChoice("min"));
    await waitFor(() => expect(urlParams().get("agg")).toBe("min"));
    await waitFor(() => expect(tag()).toBe("min"));
    m.experimentGroups.mockResolvedValue(payload());
    // The aggregate row keeps the menu open.
    fireEvent.click(aggChoice("median"));
    await waitFor(() => expect(urlParams().has("agg")).toBe(false));
    await waitFor(() => expect(tag()).toBe("median"));
  });
});

describe("live while any group runs (plan 22 F4)", () => {
  it("polls while the payload counts a running run, though no loaded row runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderBoard("/ws/test/app/my-app?group=branch");
    await screen.findByText("0.0.1-dev.x");
    expect(screen.getByText(/live · updated \d+s ago/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    const calls = m.experimentGroups.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(45_000); });
    expect(m.experimentGroups.mock.calls.length).toBeGreaterThan(calls);
  });

  it("is not live when the payload counts nothing running", async () => {
    m.experimentGroups.mockResolvedValue(payload({ running: 0 }));
    renderBoard("/ws/test/app/my-app?group=branch");
    await screen.findByText("0.0.1-dev.x");
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});
