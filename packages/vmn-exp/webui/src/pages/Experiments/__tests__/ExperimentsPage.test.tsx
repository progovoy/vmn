/** The experiments page's two views (plan 23 W1, §3.4, §10): Jobs (the
 *  default) and All runs (plan 22's board), `view=jobs|all` in the URL,
 *  else the app's last view, else Jobs. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getTotalSize: () => count * estimateSize(),
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * estimateSize(), size: estimateSize(), end: (index + 1) * estimateSize(),
      })),
  }),
}));

import { api } from "../../../api";
import { jobsPage, notFound, renderExperiments, singleRow, topRow, urlParams } from "./jobsHarness";
import { VIEW_KEY } from "../experimentsView";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const switcher = () => screen.getByRole("group", { name: "Experiments view" });
const pressed = (name: string) => within(switcher()).getByRole("button", { name }).getAttribute("aria-pressed");
const board = (rows: object[]) => Object.assign([...rows], { total: rows.length });
const facets = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, parented: 5, total: 7 };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.experimentsColumns.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([topRow(2, { name: "grid" }), singleRow(1, { name: "solo" })]));
  m.experiments.mockResolvedValue(board([singleRow(1, { name: "solo" }), singleRow(3, { name: "inner", depth: 1, kind: "inner" })]));
});

describe("Jobs | All runs", () => {
  it("opens on the Jobs view: the top-level runs only", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(pressed("Jobs")).toBe("true");
    expect(pressed("All runs")).toBe("false");
    expect(m.experimentsPaged).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({ top: true }));
    expect(m.experiments).not.toHaveBeenCalled();
  });

  it("All runs is plan 22's board, view=all, and remembered for the app", async () => {
    const first = renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    fireEvent.click(within(switcher()).getByRole("button", { name: "All runs" }));
    await screen.findByRole("link", { name: "inner" });
    expect(urlParams().get("view")).toBe("all");
    expect(pressed("All runs")).toBe("true");
    expect(localStorage.getItem(`${VIEW_KEY}:test/my-app`)).toBe("all");
    first.unmount();

    renderExperiments();
    await screen.findByRole("link", { name: "inner" });
    expect(pressed("All runs")).toBe("true");
  });

  it("the URL's view beats the remembered one, which is per app", async () => {
    localStorage.setItem(`${VIEW_KEY}:test/my-app`, "all");
    renderExperiments("/ws/test/app/my-app?view=jobs");
    await screen.findByRole("link", { name: "grid" });
    expect(pressed("Jobs")).toBe("true");
  });

  it("switching views keeps the filters", async () => {
    renderExperiments("/ws/test/app/my-app?q=metrics.loss%20%3C%201&status=failed");
    await screen.findByRole("link", { name: "grid" });
    fireEvent.click(within(switcher()).getByRole("button", { name: "All runs" }));
    await waitFor(() => expect(urlParams().get("view")).toBe("all"));
    expect(urlParams().get("q")).toBe("metrics.loss < 1");
    expect(urlParams().get("status")).toBe("failed");
  });

  it("a chart view in the URL (view=bar) is the All runs board", async () => {
    renderExperiments("/ws/test/app/my-app?view=bar");
    await screen.findByRole("link", { name: "inner" });
    expect(pressed("All runs")).toBe("true");
  });

  it("the board's Charts tab in the URL (tab=charts) is the All runs board", async () => {
    localStorage.setItem(`${VIEW_KEY}:test/my-app`, "jobs");
    renderExperiments("/ws/test/app/my-app?tab=charts");
    await screen.findByRole("link", { name: "inner" });
    expect(pressed("All runs")).toBe("true");
  });

  it("group=parent in the URL (a bookmark, a saved view) is the Jobs view, ungrouped", async () => {
    renderExperiments("/ws/test/app/my-app?view=all&group=parent");
    await screen.findByRole("link", { name: "grid" });
    expect(pressed("Jobs")).toBe("true");
    expect(m.experimentGroups).not.toHaveBeenCalled();
  });

  it("All runs is not grouped by parent run: that grouping is the Jobs view", async () => {
    m.facets.mockResolvedValue(facets);
    renderExperiments("/ws/test/app/my-app?view=all");
    await screen.findByRole("link", { name: "inner" });
    expect(m.experimentGroups).not.toHaveBeenCalled();
  });

  it("picking parent run in All runs' Group by opens the Jobs view, the filters kept", async () => {
    m.facets.mockResolvedValue(facets);
    renderExperiments("/ws/test/app/my-app?view=all&q=metrics.loss%20%3C%201");
    await screen.findByRole("link", { name: "inner" });
    fireEvent.click(screen.getByRole("button", { name: /^Group by/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "parent run" }));
    await screen.findByRole("link", { name: "grid" });
    expect(urlParams().get("view")).toBe("jobs");
    expect(urlParams().get("q")).toBe("metrics.loss < 1");
    expect(urlParams().get("group")).toBeNull();
  });

  it("an app without runs reads the same in both views", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([]));
    m.experiments.mockResolvedValue(board([]));
    const first = renderExperiments();
    expect(await screen.findByText(/No runs yet in my\/app/)).toBeInTheDocument();
    first.unmount();
    renderExperiments("/ws/test/app/my-app?view=all");
    expect(await screen.findByText(/No runs yet in my\/app/)).toBeInTheDocument();
  });
});
