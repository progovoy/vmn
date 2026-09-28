import { describe, it, expect, vi, beforeEach } from "vitest";
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
import { location, page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;

/** An outer run @1 with inner runs @2..@(n+1), and a lone run after them. */
function sweep(n: number) {
  const inner = Array.from({ length: n }, (_, k) => k + 2);
  return [
    row(1, { kind: "outer", children: inner.map(v), depth: 0, tree_status: "succeeded" }),
    ...inner.map((i) => row(i, { kind: "inner", parent: v(1), depth: 1 })),
    row(n + 2),
  ];
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
});

describe("inner runs hidden from list", () => {
  it("hides inner runs from the list and shows the outer and lone runs", async () => {
    m.experiments.mockResolvedValue(page(sweep(25)));
    renderBoard();
    // The outer run (depth=0) is visible
    await screen.findByRole("link", { name: v(1) });
    // Inner runs (depth=1) are filtered out
    expect(screen.queryByRole("link", { name: v(2) })).toBeNull();
    // The lone run after the sweep (depth=0) is visible
    expect(screen.getByRole("link", { name: v(27) })).toBeInTheDocument();
  });

  it("hides inner runs of a small sweep too", async () => {
    m.experiments.mockResolvedValue(page(sweep(3)));
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    // Inner runs are not shown even for small sweeps
    expect(screen.queryByRole("link", { name: v(2) })).toBeNull();
    // The lone run after the sweep is still visible
    expect(screen.getByRole("link", { name: v(5) })).toBeInTheDocument();
  });
});

describe("keyboard row navigation", () => {
  beforeEach(() => m.experiments.mockResolvedValue(page([row(1), row(2), row(3)])));
  const rowOf = (i: number) => screen.getByRole("link", { name: v(i) }).closest("tr")!;

  it("moves through rows with j/k and the arrows, and Enter opens the run", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    const table = screen.getByRole("grid");
    fireEvent.keyDown(table, { key: "j" });
    expect(rowOf(1)).toHaveFocus();
    fireEvent.keyDown(rowOf(1), { key: "ArrowDown" });
    expect(rowOf(2)).toHaveFocus();
    fireEvent.keyDown(rowOf(2), { key: "j" });
    fireEvent.keyDown(rowOf(3), { key: "j" });
    expect(rowOf(3)).toHaveFocus();
    fireEvent.keyDown(rowOf(3), { key: "k" });
    fireEvent.keyDown(rowOf(2), { key: "ArrowUp" });
    expect(rowOf(1)).toHaveFocus();
    fireEvent.keyDown(rowOf(1), { key: "Enter" });
    await waitFor(() => expect(location.pathname).toBe(`/ws/test/app/my-app/run/${v(1)}`));
  });

  it("keeps a single tab stop in the table", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    const stops = [1, 2, 3].map((i) => rowOf(i).getAttribute("tabindex"));
    expect(stops).toEqual(["0", "-1", "-1"]);
  });
});

describe("toggle buttons report their state", () => {
  it("marks the current chart view pressed", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard("/ws/test/app/my-app?view=bar");
    await screen.findByRole("link", { name: v(1) });
    expect(screen.getByRole("button", { name: "Bar" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Trend" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("saved views in the toolbar", () => {
  it("applies a saved view to the URL and the filter bar", async () => {
    localStorage.setItem("vmn_views:test/my-app", JSON.stringify([{ name: "fails", search: "?status=failed" }]));
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(screen.getByRole("button", { name: /views/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "fails" }));
    await waitFor(() => expect(urlParams().get("status")).toBe("failed"));
    expect(screen.getByRole("button", { name: "failed" })).toHaveAttribute("aria-pressed", "true");
    localStorage.clear();
  });
});
