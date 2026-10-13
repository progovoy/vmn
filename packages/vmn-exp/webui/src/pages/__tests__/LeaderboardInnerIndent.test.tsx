/** An opened outer run's inner runs read as its children: the whole
 *  experiment cell (name and verstr line) sits one tree level to the right,
 *  the row is marked `inner` (tinted, with a guide line), and phone cards do
 *  the same. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
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
import { NARROW_QUERY } from "../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../hooks/__tests__/fakeMedia";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const link = (i: number) => screen.findByRole("link", { name: v(i) });
const toggle = () => screen.getByRole("button", { name: new RegExp(`Expand ${v(1)}`) });
const ROWS = [
  row(1, { kind: "outer", children: [v(2)], depth: 0, parent: null }),
  row(2, { kind: "inner", parent: v(1), depth: 1 }),
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

describe("inner runs read as children of their outer run", () => {
  it("indents the whole experiment cell one level and marks the row inner", async () => {
    renderBoard();
    await link(1);
    fireEvent.click(toggle());
    const inner = await link(2);
    const outer = await link(1);

    const tree = inner.closest(".exp-tree") as HTMLElement;
    expect(tree).not.toBeNull();
    expect(tree.style.getPropertyValue("--depth")).toBe("1");
    expect(tree.querySelector(".exp-branch")).not.toBeNull();
    expect((outer.closest(".exp-tree") as HTMLElement).style.getPropertyValue("--depth")).toBe("0");

    expect(inner.closest("tr")).toHaveClass("inner");
    expect(outer.closest("tr")).not.toHaveClass("inner");
  });

  it("indents a phone card the same way", async () => {
    fakeMedia([NARROW_QUERY]);
    renderBoard();
    await link(1);
    fireEvent.click(toggle());
    const card = (await link(2)).closest("li") as HTMLElement;
    await waitFor(() => expect(card).toHaveClass("inner"));
    expect(card.style.getPropertyValue("--depth")).toBe("1");
    expect((await link(1)).closest("li")).not.toHaveClass("inner");
  });
});
