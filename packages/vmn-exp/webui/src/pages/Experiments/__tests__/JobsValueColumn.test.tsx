/** Plan 31 §2: the Outer runs row's value column shows the chosen aggregate
 *  (`job.rolled`), its header and title naming the aggregate, its units,
 *  source and coverage (plan 32); the column's menu picks `job_agg*`,
 *  round-tripped through the URL into the request. */
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
import type { JobRolled } from "../../../types";
import { job, rolled } from "../../../util/__tests__/jobFixture";
import { jobsPage, notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const DATES: Partial<JobRolled> = {
  agg: "median", by: "field:params.trade_date", source: "own", metric: "date.best_value", goal: "max",
  value: 0.65, n: 14, of: 16, verstr: "0.0.1-dev.d7",
};
const gridWith = (r: Partial<JobRolled> | null) =>
  topRow(36, { name: "lr_layers_grid", job: job({ rolled: r && rolled(r) }) });
const cell = () =>
  screen.getByRole("link", { name: "lr_layers_grid" }).closest("tr")!.querySelector('[data-col-id="value"]') as HTMLElement;
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];
const header = () => document.querySelector('th[data-col-id="value"]') as HTMLElement;
const openMenu = () => fireEvent.click(screen.getByRole("button", { name: "Pick the value's aggregate" }));
const menu = () => screen.getByRole("menu", { name: "Value aggregate" });
const choice = (section: string, name: string) =>
  within(within(menu()).getByRole("group", { name: section })).getByRole("menuitemradio", { name });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockResolvedValue({
    branches: [], metric_keys: ["date.best_value", "val_loss"], param_keys: ["trade_date"], tag_keys: ["kind"],
    param_values: { trade_date: 400 }, parented: 1, total: 9, jobs: 1, singles: 0,
  });
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([gridWith(DATES)]));
});

describe("the value cell", () => {
  it("shows rolled.value, titled by its aggregate, coverage, units and source, linked to its unit", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    const value = within(cell()).getByRole("link", { name: /0\.65/ });
    expect(value).toHaveAttribute("href", `/ws/test/app/my-app/run/${encodeURIComponent("0.0.1-dev.d7")}`);
    expect(cell().querySelector("[title]")).toHaveAttribute("title", "median of 14/16 dates' own date.best_value");
  });

  it("counts a duplicate date left out", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([gridWith({ ...DATES, n: 15, conflicts: 1 })]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cell().querySelector("[title]")!.getAttribute("title")).toMatch(/ · 1 duplicate date left out$/);
  });

  it("marks an approximate value ≈, and names a tail's percentile", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([
      gridWith({ ...DATES, agg: "best10", percentile: "p90", by: "runs", approx: true, verstr: null }),
    ]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cell().textContent).toMatch(/^≈ 0\.65/);
    expect(within(cell()).queryByRole("link")).toBeNull();
    expect(cell().querySelector("[title]")!.getAttribute("title")).toMatch(/^≈ best10 \(p90\) of 14\/16 runs'/);
  });

  it("reads — (no goal) for a metric without a goal, never a value", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([gridWith({ ...DATES, goal: null, value: null, verstr: null })]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cell().textContent).toBe("— (no goal)");
    expect(cell().querySelector("[title]")).toHaveAttribute("title", "no goal declared for date.best_value — not ranked");
  });

  it("reads — for a row the aggregate doesn't fit, with its coverage", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([gridWith({ ...DATES, value: null, n: 0, of: 0, verstr: null })]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cell().textContent).toBe("—");
    expect(cell().querySelector("[title]")).toHaveAttribute("title", "median of 0 dates' own date.best_value");
  });

  it("shows nothing taken from job.best when the row has no rolled (plan 32: no fallback)", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([gridWith(null)]));
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(cell().textContent).toBe("");
  });
});

describe("the value column's header", () => {
  it("names the aggregate and its units", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(header().textContent).toMatch(/^median · dates/);
  });

  it("sorts by job:value, best first by rolled's goal (not the main metric's)", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    fireEvent.click(screen.getByRole("button", { name: /sort by value/i }));
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:value"));
    // date.best_value goes up (the page's main val_loss goes down).
    expect(urlParams().get("order")).toBe("desc");
    await waitFor(() => expect(lastOpts()).toEqual(expect.objectContaining({ sort: "job:value", order: "desc" })));
  });
});

describe("the job_agg URL values", () => {
  it("go to the request, omitted (the app's default) when absent", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    for (const k of ["jobAgg", "jobAggBy", "jobAggValue", "jobAggMetric"]) expect(lastOpts()[k]).toBeUndefined();
  });

  it("are read from the URL into the request", async () => {
    renderExperiments("/ws/test/app/my-app?job_agg=median&job_agg_by=field:params.trade_date&job_agg_value=own&job_agg_metric=date.best_value");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    expect(lastOpts()).toEqual(expect.objectContaining({
      top: "jobs", jobAgg: "median", jobAggBy: "field:params.trade_date", jobAggValue: "own", jobAggMetric: "date.best_value",
    }));
  });
});

describe("the value column's menu", () => {
  it("checks the answered aggregate, by, value and metric", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    openMenu();
    expect(choice("Aggregate", "median")).toHaveAttribute("aria-checked", "true");
    expect(choice("By", "field:params.trade_date")).toHaveAttribute("aria-checked", "true");
    expect(choice("Value", "own")).toHaveAttribute("aria-checked", "true");
    expect(choice("Metric", "date.best_value")).toHaveAttribute("aria-checked", "true");
    // The tails name the percentile rolled's goal points at.
    expect(choice("Aggregate", "best10 (p90)")).toBeInTheDocument();
    expect(choice("Aggregate", "worst10 (p10)")).toBeInTheDocument();
    expect(choice("By", "children")).toBeInTheDocument();
    expect(choice("By", "runs")).toBeInTheDocument();
    expect(choice("By", "field:tags.kind")).toBeInTheDocument();
  });

  it("writes a pick to the URL and the request, without sorting", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "lr_layers_grid" });
    openMenu();
    fireEvent.click(choice("Aggregate", "best10 (p90)"));
    await waitFor(() => expect(urlParams().get("job_agg")).toBe("best10"));
    fireEvent.click(choice("By", "children"));
    await waitFor(() => expect(urlParams().get("job_agg_by")).toBe("children"));
    fireEvent.click(choice("Value", "best"));
    await waitFor(() => expect(urlParams().get("job_agg_value")).toBe("best"));
    fireEvent.click(choice("Metric", "val_loss"));
    await waitFor(() => expect(urlParams().get("job_agg_metric")).toBe("val_loss"));
    expect(urlParams().get("sort")).toBeNull();
    await waitFor(() => expect(lastOpts()).toEqual(expect.objectContaining({
      jobAgg: "best10", jobAggBy: "children", jobAggValue: "best", jobAggMetric: "val_loss",
    })));
  });

  it("goes back to the app's default, dropping every job_agg value", async () => {
    renderExperiments("/ws/test/app/my-app?job_agg=max&job_agg_value=best");
    await screen.findByRole("link", { name: "lr_layers_grid" });
    openMenu();
    fireEvent.click(within(menu()).getByRole("menuitem", { name: "app default" }));
    await waitFor(() => expect(urlParams().get("job_agg")).toBeNull());
    expect(urlParams().get("job_agg_value")).toBeNull();
  });
});
