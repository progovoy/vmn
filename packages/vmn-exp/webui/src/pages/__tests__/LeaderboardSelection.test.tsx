import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
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
const checkbox = (i: number) =>
  within(screen.getByRole("link", { name: v(i) }).closest("tr")!).getByRole("checkbox");

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([1, 2, 3, 4, 5].map((i) => row(i)), 900));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 900 });
});

describe("selection counter", () => {
  it("counts the selection and clears it", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}&sel=${v(2)}`);
    expect(await screen.findByText("2 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
    expect(screen.queryByText(/selected$/)).toBeNull();
  });
});

describe("shift-click range select", () => {
  it("selects every row between the last click and a shift-click", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(checkbox(2));
    fireEvent.click(checkbox(4), { shiftKey: true });
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(2), v(3), v(4)]));
  });
});

describe("select all filtered", () => {
  it("selects the whole filtered set (capped) through experiments-columns", async () => {
    m.experimentsColumns.mockResolvedValue({
      verstrs: ["a", "b", "c"], idx: [1, 2, 3], columns: {}, total: 900,
    });
    renderBoard("/ws/test/app/my-app?status=failed");
    fireEvent.click(await screen.findByRole("button", { name: /select all 500/i }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual(["a", "b", "c"]));
    expect(m.experimentsColumns).toHaveBeenCalledWith(
      "test", "my-app", [], expect.objectContaining({ status: "failed", limit: 500 }),
    );
  });

  it("falls back to the loaded rows without the columns endpoint", async () => {
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: /select all/i }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([1, 2, 3, 4, 5].map(v)));
  });
});

describe("N-run compare", () => {
  it("opens the compare table for the selected runs", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}&sel=${v(2)}&sel=${v(3)}`);
    fireEvent.click(await screen.findByRole("button", { name: /compare 3 in a table/i }));
    await waitFor(() => expect(location.pathname).toBe("/ws/test/app/my-app/compare-runs"));
    expect(urlParams().getAll("sel")).toEqual([v(1), v(2), v(3)]);
  });
});
