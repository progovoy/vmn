import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";

// Counts how often the trend chart's module is loaded: the Runs tab must not
// load chart code at all.
const charts = vi.hoisted(() => ({ trendLoads: 0 }));

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
vi.mock("../../components/ParamPlots", () => {
  charts.trendLoads += 1;
  return { default: () => <div>trend-chart</div> };
});
vi.mock("../../components/MetricBarChart", () => ({ default: () => <div>bar-chart</div> }));
vi.mock("../../components/ParallelCoordinates", () => ({
  default: ({ onBrush }: { onBrush?: (i: number[] | null) => void }) => (
    <button onClick={() => onBrush?.([1])}>fake-brush</button>
  ),
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
const tab = (name: string) => screen.getByRole("tab", { name });
const grid = () => screen.getByRole("grid", { name: "experiments" });
const tableVerstrs = () =>
  [...grid().querySelectorAll("a.run-link")].map((a) => a.getAttribute("title"));
const follows = (a: Element, b: Element) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  // Three of 900 loaded: a chart would ask experiments-columns for the rest.
  m.experiments.mockResolvedValue(page([1, 2, 3].map((i) => row(i, { metrics: { loss: i } })), 900));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 900 });
  m.experimentsColumns.mockResolvedValue({
    verstrs: [v(1), v(2), v(3)], idx: [1, 2, 3], columns: { "metrics.loss": [1, 2, 3] }, total: 3,
  });
});

describe("the board opens on its runs", () => {
  // First in the file: the module counter is per file.
  it("loads no chart code and fetches no chart data until the Charts tab opens", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(m.experimentsColumns).not.toHaveBeenCalled();
    expect(charts.trendLoads).toBe(0);

    fireEvent.click(tab("Charts"));
    expect(await screen.findByText("trend-chart")).toBeInTheDocument();
    expect(charts.trendLoads).toBe(1);
    await waitFor(() => expect(m.experimentsColumns).toHaveBeenCalledTimes(1));
  });

  it("shows the runs table right under a Runs/Charts switcher, with no chart", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    expect(screen.getByRole("tablist", { name: "Board view" })).toBeInTheDocument();
    expect(tab("Runs")).toHaveAttribute("aria-selected", "true");
    expect(tab("Charts")).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByRole("button", { name: "Trend" })).toBeNull();
    expect(screen.queryByText("trend-chart")).toBeNull();
    expect(within(screen.getByRole("tabpanel")).getByRole("grid", { name: "experiments" })).toBeInTheDocument();
    expect(follows(screen.getByRole("tablist"), grid())).toBe(true);
  });

  it("opens the charts above the same table on the Charts tab, and keeps the tab in the URL", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    fireEvent.click(tab("Charts"));
    await waitFor(() => expect(urlParams().get("tab")).toBe("charts"));
    const chart = await screen.findByText("trend-chart");
    expect(tab("Charts")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Trend" })).toHaveAttribute("aria-pressed", "true");
    expect(follows(chart, grid())).toBe(true);
    expect(tableVerstrs()).toEqual([v(1), v(2), v(3)]);

    fireEvent.click(tab("Runs"));
    await waitFor(() => expect(urlParams().get("tab")).toBeNull());
    expect(screen.queryByText("trend-chart")).toBeNull();
  });
});

describe("old links and saved views", () => {
  it("opens the Charts tab for a URL that names a chart view", async () => {
    renderBoard("/ws/test/app/my-app?view=bar");
    expect(await screen.findByText("bar-chart")).toBeInTheDocument();
    expect(tab("Charts")).toHaveAttribute("aria-selected", "true");
  });

  it("stays on the Runs tab when the URL says so, chart view or not", async () => {
    renderBoard("/ws/test/app/my-app?view=bar&tab=runs");
    await screen.findByRole("link", { name: v(1) });
    expect(tab("Runs")).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("bar-chart")).toBeNull();
  });

  it("keeps the Charts tab when the chart goes back to the default view", async () => {
    renderBoard("/ws/test/app/my-app?view=bar");
    fireEvent.click(await screen.findByRole("button", { name: "Trend" }));
    expect(await screen.findByText("trend-chart")).toBeInTheDocument();
    expect(urlParams().get("view")).toBeNull();
    expect(urlParams().get("tab")).toBe("charts");
    expect(tab("Charts")).toHaveAttribute("aria-selected", "true");
  });

  it("captures the open tab in a saved view", async () => {
    renderBoard("/ws/test/app/my-app?tab=charts");
    await screen.findByText("trend-chart");
    fireEvent.click(screen.getByRole("button", { name: /views/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "charted" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const saved = JSON.parse(localStorage.getItem("vmn_views:test/my-app") ?? "[]");
    expect(new URLSearchParams(saved[0].search).get("tab")).toBe("charts");
  });
});

describe("the parallel brush", () => {
  it("narrows the rows on the Charts tab only, and goes with the chart", async () => {
    renderBoard("/ws/test/app/my-app?view=parallel");
    fireEvent.click(await screen.findByRole("button", { name: "fake-brush" }));
    await waitFor(() => expect(tableVerstrs()).toEqual([v(2)]));

    fireEvent.click(tab("Runs"));
    await waitFor(() => expect(tableVerstrs()).toEqual([v(1), v(2), v(3)]));
    fireEvent.click(tab("Charts"));
    await screen.findByRole("button", { name: "fake-brush" });
    expect(tableVerstrs()).toEqual([v(1), v(2), v(3)]);
  });
});

describe("the switcher's keyboard", () => {
  it("moves between the tabs with the arrow, Home and End keys, one tab stop", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    expect(tab("Runs")).toHaveAttribute("tabindex", "0");
    expect(tab("Charts")).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(tab("Runs"), { key: "ArrowRight" });
    await waitFor(() => expect(tab("Charts")).toHaveAttribute("aria-selected", "true"));
    expect(tab("Charts")).toHaveFocus();
    expect(tab("Charts")).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(tab("Charts"), { key: "Home" });
    await waitFor(() => expect(tab("Runs")).toHaveAttribute("aria-selected", "true"));
    expect(tab("Runs")).toHaveFocus();
    fireEvent.keyDown(tab("Runs"), { key: "End" });
    await waitFor(() => expect(tab("Charts")).toHaveAttribute("aria-selected", "true"));
    fireEvent.keyDown(tab("Charts"), { key: "ArrowLeft" });
    await waitFor(() => expect(tab("Runs")).toHaveAttribute("aria-selected", "true"));
  });
});
