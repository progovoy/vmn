/** The Charts tab follows the selection (plan 22 F7): with rows selected it
 *  plots only them, under a `Showing N selected · Show all` note; Show all
 *  plots every filtered run again and keeps the selection. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

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
vi.mock("../../components/MetricBarChart", () => ({
  default: ({ rows }: { rows: { verstr: string }[] }) => <div>bar:{rows.map((r) => r.verstr).join(",")}</div>,
}));
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
const v = (i: number) => `0.0.${i}-dev.x`;
// One row loaded of three, so the chart plots the columns endpoint's full set.
const cols = {
  verstrs: [v(1), v(2), v(3)], idx: [1, 2, 3],
  columns: { "metrics.loss": [0.3, 0.2, 0.1] }, total: 3,
};
const ALL = `bar:${v(1)},${v(2)},${v(3)}`;
const board = (sel: string) => renderBoard(`/ws/test/app/my-app?view=bar${sel}`);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.3 } })], 3));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 3 });
  m.experimentsColumns.mockResolvedValue(cols);
});

describe("the Charts tab with rows selected", () => {
  it("plots only the selected runs, saying so", async () => {
    board(`&sel=${v(2)}&sel=${v(3)}`);
    expect(await screen.findByText(`bar:${v(2)},${v(3)}`)).toBeInTheDocument();
    expect(screen.getByText("Showing 2 selected")).toBeInTheDocument();
    expect(screen.queryByText("charting 3 of 3 runs")).toBeNull();
  });

  it("Show all plots every filtered run and keeps the selection", async () => {
    board(`&sel=${v(2)}&sel=${v(3)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Show all" }));
    expect(await screen.findByText(ALL)).toBeInTheDocument();
    expect(screen.getByText("charting 3 of 3 runs")).toBeInTheDocument();
    expect(urlParams().getAll("sel")).toEqual([v(2), v(3)]);
    fireEvent.click(screen.getByRole("button", { name: "Show 2 selected" }));
    expect(await screen.findByText(`bar:${v(2)},${v(3)}`)).toBeInTheDocument();
  });

  it("plots the selection again once it changes after Show all", async () => {
    board(`&sel=${v(2)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Show all" }));
    await screen.findByText(ALL);
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${v(1)}` }));
    expect(await screen.findByText(`bar:${v(1)},${v(2)}`)).toBeInTheDocument();
    expect(screen.getByText("Showing 2 selected")).toBeInTheDocument();
  });

  it("plots every filtered run without a selection", async () => {
    board("");
    expect(await screen.findByText(ALL)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all" })).toBeNull();
  });
});
