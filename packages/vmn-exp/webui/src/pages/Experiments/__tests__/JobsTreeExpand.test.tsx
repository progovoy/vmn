/** Plan 28 N6: an Outer runs row opens its tree in place (its expander), a
 *  single run has none. */
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
vi.mock("../../../apiTree", async (orig) => ({
  ...(await orig<typeof import("../../../apiTree")>()),
  fetchChildren: vi.fn(),
}));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
/** Each virtualizer's scroll element getter, to see which box it scrolls with. */
const scrollers = vi.hoisted(() => [] as (() => Element | null)[]);
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize, getScrollElement }: {
    count: number; estimateSize: (i: number) => number; getScrollElement: () => Element | null;
  }) => (scrollers.push(getScrollElement), {
    getTotalSize: () => Array.from({ length: count }, (_, i) => estimateSize(i)).reduce((a, b) => a + b, 0),
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: estimateSize(index), end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../../api";
import { fetchChildren } from "../../../apiTree";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const fetched = fetchChildren as unknown as ReturnType<typeof vi.fn>;
const GRID = topRow(36, { name: "lr_layers_grid" });
const SOLO = singleRow(12, { name: "solo" });
const CHILD = { ...singleRow(37, { name: "trial-1", parent: GRID.verstr, depth: 1 }), open: false };

beforeEach(() => {
  vi.clearAllMocks();
  scrollers.length = 0;
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, SOLO]));
  fetched.mockResolvedValue({ rows: [CHILD], total: 1, next_cursor: null, tree_columns: {} });
});

describe("an Outer runs row's tree", () => {
  it("opens under the row from its expander, and folds again", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(screen.queryByRole("button", { name: "expand solo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "expand lr_layers_grid" }));
    expect(await screen.findByRole("treegrid", { name: "runs of lr_layers_grid" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "trial-1" })).toBeInTheDocument();
    expect(fetched.mock.calls[0][2]).toBe(GRID.verstr);
    fireEvent.click(screen.getByRole("button", { name: "collapse lr_layers_grid" }));
    await waitFor(() => expect(screen.queryByRole("treegrid")).toBeNull());
  });

  it("flows inline in the board's one scroll box, with no scroll box of its own", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: "expand lr_layers_grid" }));
    await screen.findByRole("link", { name: "trial-1" });
    const scroller = screen.getByRole("grid", { name: "outer runs" }).closest<HTMLElement>(".tbl-scroll")!;
    const tree = screen.getByRole("treegrid");
    expect(tree.closest<HTMLElement>("tr.jobs-tree-slot")!.style.height).toBe("");
    for (let el = tree.parentElement; el && el !== scroller; el = el.parentElement) {
      expect(el.style.maxHeight).toBe("");
      expect(el.style.overflow).toBe("");
    }
    for (const scrollElement of scrollers) expect(scrollElement()).toBe(scroller);
  });
});
