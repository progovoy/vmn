/** The Jobs view (plan 23 W1, §3.1): one row per top-level run, a job's
 *  progress, best, spread, size, failures, throughput and ETA. */
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
import { job } from "../../../util/__tests__/jobFixture";
import { jobsPage, location, notFound, renderExperiments, singleRow, topRow, selection, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(36, { name: "lr_layers_grid", branch: "feature-x" });
const SOLO = singleRow(12, { name: "solo", base_version: "0.3.0", metrics: { val_loss: 0.4 } });
const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
const cellOf = (name: string, col: string) => rowOf(name).querySelector(`[data-col-id="${col}"]`)!;
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, SOLO]));
});

describe("a job's row", () => {
  it("links its name to the run page and carries the tree status", async () => {
    renderExperiments();
    const link = await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(link).toHaveAttribute("href", `/ws/test/app/my-app/run/${encodeURIComponent(GRID.verstr)}`);
    expect(cellOf("lr_layers_grid", "idx").textContent).toBe("@36");
    expect(within(cellOf("lr_layers_grid", "status") as HTMLElement).getByText(/running/i)).toBeInTheDocument();
  });

  it("shows the job's progress under its name", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const name = cellOf("lr_layers_grid", "name");
    expect(name.querySelector(".job-progress-text")?.textContent).toBe("1,412/2,000 · 3 failed · 41/min · ETA 14m");
    expect(name.querySelectorAll(".job-bar-seg").length).toBeGreaterThan(0);
  });

  it("shows the best run's value with the goal arrow and its @N linked", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const best = cellOf("lr_layers_grid", "best") as HTMLElement;
    expect(best.textContent).toContain("0.182");
    expect(best.textContent).toContain("↓");
    expect(within(best).getByRole("link", { name: "@1903" }))
      .toHaveAttribute("href", `/ws/test/app/my-app/run/${encodeURIComponent("0.0.1-dev.t1903")}`);
  });

  it("a job without a best (no goal declared) reads a dash that says why", async () => {
    m.metricsSchema.mockResolvedValue({});
    m.experimentsPaged.mockResolvedValue(jobsPage([
      topRow(36, { name: "lr_layers_grid", job: job({ metric: "loss", best: null, best_verstr: null, best_idx: null }) }),
    ]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const dash = within(cellOf("lr_layers_grid", "best") as HTMLElement).getByText("—");
    expect(dash).toHaveAttribute("title", "no goal declared for loss — not ranked");
  });

  it("draws the spread and names what it shows", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const svg = cellOf("lr_layers_grid", "spread").querySelector("svg")!;
    expect(svg.getAttribute("aria-label")).toBe("distribution of val_loss over 26 runs");
  });

  it("counts runs, failed %, throughput and ETA in their columns", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cellOf("lr_layers_grid", "runs").textContent).toBe("1,415");
    expect(cellOf("lr_layers_grid", "failed").textContent).toBe("0.2%");
    expect(cellOf("lr_layers_grid", "throughput").textContent).toBe("41/min");
    expect(cellOf("lr_layers_grid", "eta").textContent).toBe("14m");
    expect(cellOf("lr_layers_grid", "branch").textContent).toBe("feature-x");
  });

  it("a single run reads its base (its branch is the Branch column's), and its own value as best", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "solo" });
    expect(cellOf("solo", "name").textContent).toContain("0.3.0");
    expect(cellOf("solo", "name").textContent).not.toContain("main");
    expect(cellOf("solo", "branch").textContent).toBe("main");
    expect(cellOf("solo", "best").textContent).toContain("0.4");
    expect(cellOf("solo", "runs").textContent).toBe("");
  });
});

describe("a finished job's row", () => {
  const ended = (extra: Partial<ReturnType<typeof job>> = {}) => topRow(40, {
    name: "done_grid", status: "succeeded", tree_status: "succeeded",
    job: job({
      total: 20, done: 20, expected: 20, throughput_per_min: 0, eta_sec: null,
      counts: { running: 0, waiting: 0, succeeded: 20, failed: 0, stuck: 0 },
      finished_at: new Date(Date.now() - 3 * 86_400_000 - 60_000).toISOString(), ...extra,
    }),
  });

  it("dashes its rate with a reason, and its ETA says when it finished", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([ended()]));
    renderExperiments();
    await screen.findByRole("link", { name: "done_grid" });
    expect(cellOf("done_grid", "throughput").textContent).toBe("—");
    expect(cellOf("done_grid", "throughput").getAttribute("title")).toBe("the outer run has ended");
    expect(cellOf("done_grid", "eta").textContent).toBe("finished 3d ago");
  });

  it("counts the runs an ended job never started", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([ended({ expected: 200 })]));
    renderExperiments();
    await screen.findByRole("link", { name: "done_grid" });
    expect(cellOf("done_grid", "eta").textContent).toBe("ended · 180 never started");
  });

  it("a job with runs left and none finishing is stalled", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([topRow(36, { name: "slow", job: job({ eta_sec: null, throughput_per_min: 0 }) })]));
    renderExperiments();
    await screen.findByRole("link", { name: "slow" });
    expect(cellOf("slow", "eta").textContent).toBe("stalled");
    expect(cellOf("slow", "throughput").textContent).toBe("—");
  });
});

describe("the Jobs view's columns", () => {
  const head = (col: string) =>
    screen.getByRole("grid", { name: "outer runs" }).querySelector(`th[data-col-id="${col}"]`) as HTMLElement;

  it("fit a six-digit @N and the longest status pill", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(parseInt(head("idx").style.width, 10)).toBeGreaterThanOrEqual(72);
    expect(parseInt(head("status").style.width, 10)).toBeGreaterThanOrEqual(124);
  });

  it("keep the header in view while the rows scroll", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(head("name").style.position).toBe("sticky");
  });
});

describe("the Jobs view", () => {
  it("asks for top-level rows, newest first", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastOpts()).toEqual(expect.objectContaining({ top: true, sort: "idx", offset: 0 }));
  });

  it("sorts by a header: the job sort keys of the contract", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: /sort by runs/i }));
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:total"));
    expect(urlParams().get("order")).toBe("desc");
    await waitFor(() => expect(lastOpts()).toEqual(expect.objectContaining({ sort: "job:total", order: "desc" })));
    fireEvent.click(screen.getByRole("button", { name: /sort by best/i }));
    // val_loss goes down: best first is ascending.
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:best"));
    expect(urlParams().get("order")).toBe("asc");
    expect(rowOf("lr_layers_grid").closest("table")!.querySelector('th[aria-sort="ascending"]')).not.toBeNull();
  });

  it("passes the filter bar's query and status to the server", async () => {
    renderExperiments("/ws/test/app/my-app?q=params.lr%20%3E%200.1&status=failed");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastOpts()).toEqual(expect.objectContaining({ query: "params.lr > 0.1", status: "failed", top: true }));
  });

  it("groups jobs: Group by asks the grouped endpoint for top-level rows", async () => {
    m.experimentGroups.mockResolvedValue({
      groups: [{
        key: "feature-x", label: "branch = feature-x", target: null, loose: false,
        counts: { total: 1, running: 1, waiting: 0, done: 0, failed: 0, stuck: 0 },
        aggregates: {}, rows: [GRID], rows_total: 1, rows_unfiltered: 1,
      }],
      total_groups: 1, total_rows: 1, aggregate: "mean", running: 1,
    });
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: /^Group by/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "branch" }));
    await screen.findByText("branch = feature-x");
    expect(urlParams().get("group")).toBe("branch");
    expect(m.experimentGroups).toHaveBeenCalledWith("test", "my-app", expect.objectContaining({ group: "branch", top: true }));
    expect(screen.getByRole("link", { name: "lr_layers_grid" })).toBeInTheDocument();
  });

  it("a saved view's filters show in the filter bar", async () => {
    localStorage.setItem("vmn_views:test/my-app", JSON.stringify([{ name: "big lr", search: "?q=params.lr%20%3E%201" }]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: /^views/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "big lr" }));
    await waitFor(() => expect(urlParams().get("q")).toBe("params.lr > 1"));
    expect(within(screen.getByRole("list", { name: "Active filters" })).getByText(/params\.lr > 1/)).toBeInTheDocument();
  });

  it("density=compact gives one-line rows", async () => {
    renderExperiments("/ws/test/app/my-app?density=compact");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(rowOf("lr_layers_grid").style.height).toBe("32px");
    expect(screen.getByRole("grid", { name: "outer runs" })).toHaveClass("compact");
  });

  it("moves with j and opens a row with Enter", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.keyDown(document.body, { key: "j" });
    await waitFor(() => expect(document.activeElement).toBe(rowOf("lr_layers_grid")));
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    await waitFor(() => expect(location.pathname).toBe(`/ws/test/app/my-app/run/${encodeURIComponent(GRID.verstr)}`));
  });

  it("x selects the row under the cursor", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.keyDown(document.body, { key: "j" });
    await waitFor(() => expect(document.activeElement).toBe(rowOf("lr_layers_grid")));
    fireEvent.keyDown(document.activeElement!, { key: "x" });
    await waitFor(() => expect(selection()).toEqual([GRID.verstr]));
  });

  it("shows skeleton rows while the first page loads", async () => {
    m.experimentsPaged.mockReturnValue(new Promise(() => {}));
    const { container } = renderExperiments();
    await waitFor(() => expect(container.querySelectorAll(".skeleton-row").length).toBeGreaterThan(0));
  });

  it("shows the server's error", async () => {
    m.experimentsPaged.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    renderExperiments();
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });

  it("offers more jobs past the first page", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([GRID, SOLO], 120));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    m.experimentsPaged.mockResolvedValue(jobsPage([topRow(5, { name: "older", job: job() })], 120));
    fireEvent.click(screen.getByRole("button", { name: /Load more \(118 remaining\)/ }));
    await screen.findByRole("link", { name: "older" });
    expect(lastOpts()).toEqual(expect.objectContaining({ top: true, offset: 2 }));
  });
});
