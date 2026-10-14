/** The experiments page's one view switch, Jobs | Single runs | All runs
 *  (plan 23 §3.1): the jobs are not buried under thousands of single runs.
 *  `kind=jobs|singles` in the URL, else jobs when the app has any; requests
 *  send `top=jobs|singles`. An app without jobs reads Runs | All runs. */
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
import { jobsPage, notFound, renderExperiments, singleRow, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 99_600 };
const WITH_JOBS = { ...FACETS, parented: 80_000, jobs: 20, singles: 19_580 };
const switcher = () => screen.queryByRole("group", { name: "Experiments view" });
const options = () => within(switcher()!).getAllByRole("button").map((b) => b.textContent);
const pressed = (name: RegExp) => within(switcher()!).getByRole("button", { name }).getAttribute("aria-pressed");
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(WITH_JOBS);
  m.experimentsPaged.mockResolvedValue(jobsPage([topRow(2, { name: "grid" })], 20));
});

describe("Jobs | Single runs | All runs", () => {
  it("is one switch beside the title, Jobs and Single runs counted, then All runs", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(screen.getAllByRole("button", { name: /^Single runs/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /^Jobs/ })).toHaveLength(1);
    expect(options()).toEqual(["Jobs (20)", "Single runs (19,580)", "All runs"]);
    expect(screen.queryByRole("group", { name: "Jobs or single runs" })).toBeNull();
  });

  it("opens on the jobs, counting each side from the facets", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(within(switcher()!).getByRole("button", { name: "Jobs (20)" })).toHaveAttribute("aria-pressed", "true");
    expect(within(switcher()!).getByRole("button", { name: "Single runs (19,580)" })).toHaveAttribute("aria-pressed", "false");
    expect(lastOpts()).toEqual(expect.objectContaining({ top: "jobs" }));
    expect(screen.getByText("20 jobs")).toBeInTheDocument();
  });

  it("switches to the single runs, kind=singles in the URL", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })], 19_580));
    fireEvent.click(within(switcher()!).getByRole("button", { name: /^Single runs/ }));
    await screen.findByRole("link", { name: "solo" });
    expect(urlParams().get("kind")).toBe("singles");
    expect(lastOpts()).toEqual(expect.objectContaining({ top: "singles", offset: 0 }));
    expect(pressed(/^Single runs/)).toBe("true");
    expect(screen.getByText("19,580 single runs")).toBeInTheDocument();
  });

  it("kind= in the URL wins", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })]));
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await screen.findByRole("link", { name: "solo" });
    expect(lastOpts()).toEqual(expect.objectContaining({ top: "singles" }));
    expect(m.experimentsPaged.mock.calls.every(([, , o]) => o.top === "singles")).toBe(true);
  });

  it("waits for the facets before choosing a side", async () => {
    m.facets.mockReturnValue(new Promise(() => {}));
    renderExperiments();
    await new Promise((r) => setTimeout(r, 20));
    expect(m.experimentsPaged).not.toHaveBeenCalled();
  });

  it("leaves the counts out when the facets have none", async () => {
    m.facets.mockResolvedValue({ ...FACETS, parented: 5 });
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(within(switcher()!).getByRole("button", { name: "Jobs" })).toHaveAttribute("aria-pressed", "true");
    expect(within(switcher()!).getByRole("button", { name: "Single runs" })).toBeInTheDocument();
  });

  it("an app without jobs reads Runs | All runs and lists its single runs", async () => {
    m.facets.mockResolvedValue({ ...FACETS, parented: 0, jobs: 0, singles: 3 });
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })]));
    renderExperiments("/ws/test/app/my-app?kind=jobs");
    await screen.findByRole("link", { name: "solo" });
    expect(options()).toEqual(["Runs", "All runs"]);
    expect(pressed(/^Runs/)).toBe("true");
    expect(lastOpts()).toEqual(expect.objectContaining({ top: true }));
  });

  it("without facets it lists every top-level run, Runs | All runs", async () => {
    m.facets.mockRejectedValue(notFound());
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(options()).toEqual(["Runs", "All runs"]);
    expect(lastOpts()).toEqual(expect.objectContaining({ top: true }));
  });

  it("an empty side says so instead of reading as an app without runs", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([]));
    renderExperiments("/ws/test/app/my-app?kind=singles");
    expect(await screen.findByText("No single runs yet.")).toBeInTheDocument();
    expect(screen.queryByText(/No runs yet in/)).toBeNull();
    expect(switcher()).not.toBeNull();
  });

  it("filtered down to nothing, says no job matches", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([]));
    renderExperiments("/ws/test/app/my-app?status=failed");
    expect(await screen.findByText("No jobs match the filters.")).toBeInTheDocument();
  });

  it("the CLI line lists what the view shows", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(screen.getByText(/vmn-exp list my\/app --query 'depth = 0 and kind = "outer"'/)).toBeInTheDocument();
  });

  it("leaving for All runs drops kind=", async () => {
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalled());
    fireEvent.click(within(screen.getByRole("group", { name: "Experiments view" })).getByRole("button", { name: "All runs" }));
    await waitFor(() => expect(urlParams().get("view")).toBe("all"));
    expect(urlParams().has("kind")).toBe(false);
  });

  it("from All runs, Single runs opens the Jobs view on the single runs", async () => {
    m.experiments.mockResolvedValue(Object.assign([], { total: 0 }));
    m.experimentsColumns.mockRejectedValue(notFound());
    renderExperiments("/ws/test/app/my-app?view=all");
    const single = await screen.findByRole("button", { name: /^Single runs/ });
    expect(pressed(/^All runs/)).toBe("true");
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })]));
    fireEvent.click(single);
    await screen.findByRole("link", { name: "solo" });
    expect(urlParams().get("view")).toBe("jobs");
    expect(urlParams().get("kind")).toBe("singles");
    expect(pressed(/^Single runs/)).toBe("true");
  });
});
