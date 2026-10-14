/** An outer run carries its `outer · N runs` badge on All runs' name cell
 *  (beside its tree status) and on the phone's cards. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 48, size: 48 })),
  }),
}));

import { api } from "../../api";
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const ROWS = [
  row(1, {
    name: "kfold-cv", kind: "outer", children: [v(2), v(3)], depth: 0, parent: null,
    status: "succeeded", tree_status: "failed",
  }),
  row(2, { kind: "inner", parent: v(1), depth: 1, status: "failed" }),
  row(3, { kind: "inner", parent: v(1), depth: 1 }),
  row(4, { name: "solo", kind: "single", children: [] }),
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(ROWS));
  m.experimentsPaged.mockResolvedValue({ rows: ROWS, total: ROWS.length });
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
});
afterEach(dropFakeMedia);

describe("All runs' name cell", () => {
  it("keeps the tree status and adds the outer badge, linked to the outer run's page", async () => {
    fakeMedia([]);
    renderBoard();
    const name = await screen.findByRole("link", { name: "kfold-cv" });
    const cell = name.closest("td") as HTMLElement;
    expect(cell.querySelector(".tree-roll")).toHaveTextContent("tree failed");
    expect(within(cell).getByRole("link", { name: "outer · 2 runs" }))
      .toHaveAttribute("href", `/ws/test/app/my-app/run/${v(1)}`);
  });

  it("gives a single run no badge", async () => {
    fakeMedia([]);
    renderBoard();
    const cell = (await screen.findByRole("link", { name: "solo" })).closest("td") as HTMLElement;
    expect(cell.querySelector(".outer-badge")).toBeNull();
  });
});

describe("the leaderboard cards", () => {
  it("badge an outer run's card", async () => {
    fakeMedia([NARROW_QUERY]);
    renderBoard();
    await screen.findByRole("list", { name: "experiments" });
    const card = screen.getByRole("link", { name: "kfold-cv" }).closest("li") as HTMLElement;
    expect(within(card).getByRole("link", { name: "outer · 2 runs" }))
      .toHaveAttribute("href", `/ws/test/app/my-app/run/${v(1)}`);
    const solo = screen.getByRole("link", { name: "solo" }).closest("li") as HTMLElement;
    expect(solo.querySelector(".outer-badge")).toBeNull();
  });
});
