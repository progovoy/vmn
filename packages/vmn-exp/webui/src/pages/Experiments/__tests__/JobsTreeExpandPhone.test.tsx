/** Plan 28 N6 follow-up: on a phone an Outer runs card opens its tree in
 *  place from its expander too; a single run's card has none. */
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
vi.mock("../../../apiTree", async (orig) => ({
  ...(await orig<typeof import("../../../apiTree")>()),
  fetchChildren: vi.fn(),
}));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 48, size: 48, end: (index + 1) * 48 })),
  }),
}));

import { api } from "../../../api";
import { fetchChildren } from "../../../apiTree";
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";
import { NARROW_QUERY } from "../../../hooks/useMediaQuery";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const fetched = fetchChildren as unknown as ReturnType<typeof vi.fn>;
const GRID = topRow(36, { name: "lr_layers_grid" });
const SOLO = singleRow(12, { name: "solo" });
const CHILD = { ...singleRow(37, { name: "trial-1", parent: GRID.verstr, depth: 1 }), open: false };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  fakeMedia([NARROW_QUERY]);
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, SOLO]));
  fetched.mockResolvedValue({ rows: [CHILD], total: 1, next_cursor: null, tree_columns: {} });
});
afterEach(dropFakeMedia);

describe("an Outer runs card's tree", () => {
  it("opens under the card from its expander, and folds again", async () => {
    renderExperiments();
    const link = await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(link.closest("li")).toHaveClass("lb-mcard");
    expect(screen.queryByRole("button", { name: "expand solo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "expand lr_layers_grid" }));
    expect(await screen.findByRole("treegrid", { name: "runs of lr_layers_grid" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "trial-1" })).toBeInTheDocument();
    expect(fetched.mock.calls[0][2]).toBe(GRID.verstr);
    fireEvent.click(screen.getByRole("button", { name: "collapse lr_layers_grid" }));
    await waitFor(() => expect(screen.queryByRole("treegrid")).toBeNull());
  });

  it("opening it does not open the run page", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: "expand lr_layers_grid" }));
    await screen.findByRole("treegrid");
    expect(screen.queryByText("run page")).toBeNull();
  });
});
