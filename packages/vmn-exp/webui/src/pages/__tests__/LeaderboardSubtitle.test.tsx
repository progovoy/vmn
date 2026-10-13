import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";

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
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

/** Build top-level rows (depth 0) plus some inner rows (depth 1). */
function makeRowsWithInner(topCount: number, innerCount: number) {
  const rows = [];
  for (let i = 0; i < topCount; i++) {
    rows.push(row(i + 1, { depth: 0, kind: i % 3 === 0 ? "outer" : "single" }));
  }
  for (let i = 0; i < innerCount; i++) {
    rows.push(row(topCount + i + 1, { depth: 1, kind: "inner" }));
  }
  return rows;
}

/** Return the subtitle text from the .page-sub element. */
function subtitle() {
  return document.querySelector(".page-sub")?.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("Leaderboard subtitle (A5)", () => {
  it("shows 'N runs . M incl. inner' when there are inner runs but no filter", async () => {
    const rows = makeRowsWithInner(10, 5);
    // total from server includes inner runs
    m.experiments.mockResolvedValue(page(rows, rows.length));
    renderBoard();
    await waitFor(() => {
      const sub = subtitle();
      // Should show top-level count and "incl. inner"
      expect(sub).toContain("10 runs");
      expect(sub).toContain("incl. inner");
    });
  });

  it("shows just 'N runs' when there are no inner runs and no filter", async () => {
    const rows = makeRowsWithInner(10, 0);
    m.experiments.mockResolvedValue(page(rows, rows.length));
    renderBoard();
    await waitFor(() => {
      const sub = subtitle();
      expect(sub).toContain("10 runs");
      expect(sub).not.toContain("incl. inner");
    });
  });

  it("shows 'X of N runs' when a filter is active", async () => {
    const rows = makeRowsWithInner(5, 2);
    // When filtering by status, the filtered set is smaller than total
    m.experiments.mockResolvedValue(page(rows, rows.length));
    // Render with a status filter in the URL
    renderBoard("/ws/test/app/my-app?status=succeeded");
    await waitFor(() => {
      const sub = subtitle();
      expect(sub).toContain("of");
      expect(sub).toContain("runs");
    });
  });
});
