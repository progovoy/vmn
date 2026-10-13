import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderBoard, row, page } from "./leaderboardHarness";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
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

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  experimentsPaged: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

const KEYS = 300;
const wide = () => Object.fromEntries(Array.from({ length: KEYS }, (_, k) => [`k${String(k).padStart(3, "0")}`, k]));

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experimentsPaged?.mockResolvedValue(undefined);
  mockedApi.experiments.mockResolvedValue(page([row(1, { metrics: wide() }), row(2, { metrics: wide() })]));
});

const bodyRow = () => document.querySelector("tbody tr[data-row-index]") as HTMLTableRowElement;
const headIds = () => [...document.querySelectorAll("thead th[data-col-id]")].map((th) => th.getAttribute("data-col-id"));

describe("a leaderboard with hundreds of metric columns", () => {
  it("renders the columns in view, not all of them", async () => {
    renderBoard();
    await waitFor(() => expect(bodyRow()).toBeTruthy());
    expect(bodyRow().children.length).toBeLessThan(KEYS / 2);
    expect(headIds()).toContain("m:k000");
    expect(headIds()).not.toContain("m:k299");
    // Header, colgroup and rows keep one cell per column, gaps included.
    const cols = document.querySelectorAll("table[aria-label='experiments'] colgroup col").length;
    expect(document.querySelectorAll("thead tr:last-child th").length).toBe(cols);
    expect(bodyRow().children.length).toBe(cols);
  });

  it("brings far columns in when scrolled sideways", async () => {
    renderBoard();
    await waitFor(() => expect(bodyRow()).toBeTruthy());
    const scroller = document.querySelector(".tbl-scroll") as HTMLElement;
    const table = document.querySelector("table[aria-label='experiments']") as HTMLElement;
    scroller.scrollLeft = Number.parseFloat(table.style.width) - 1000;
    fireEvent.scroll(scroller);
    await waitFor(() => expect(headIds()).toContain("m:k299"));
    expect(headIds()).not.toContain("m:k000");
  });
});
