/** Plan 32 F2/F14 on the Jobs view: a declared rate column apart from the
 *  runs' throughput, each sorting by what it shows, and a "when" that says
 *  `created` for an outer run that never started. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
import { jobsPage, notFound, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000 - 60_000).toISOString();
const STARTED = hoursAgo(2);
const CREATED = hoursAgo(3);
const DATES = topRow(36, {
  name: "dates_grid",
  job: job({
    declared_progress: { done: 41, total: 60, unit: "dates", rate_per_min: 0.34 },
    progress_source: "declared", when_at: STARTED, when_source: "started",
  }),
});
const QUEUED = topRow(37, { name: "queued", started_at: null, job: job({ when_at: CREATED, when_source: "created" }) });
const cellOf = (name: string, col: string) =>
  screen.getByRole("link", { name }).closest("tr")!.querySelector(`[data-col-id="${col}"]`)!;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([DATES, QUEUED]));
});

describe("the rate and throughput columns", () => {
  it("show the declared rate and the runs' throughput apart", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "dates_grid" });
    expect(cellOf("dates_grid", "rate").textContent).toBe("20 dates/h");
    expect(cellOf("dates_grid", "throughput").textContent).toBe("41/min");
    expect(cellOf("queued", "rate").textContent).toBe("—");
    expect(cellOf("queued", "throughput").textContent).toBe("41/min");
  });

  it("sort by what they show", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "dates_grid" });
    fireEvent.click(screen.getByRole("button", { name: /sort by declared rate/i }));
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:rate"));
    fireEvent.click(screen.getByRole("button", { name: /sort by throughput, runs finished a minute/i }));
    await waitFor(() => expect(urlParams().get("sort")).toBe("job:throughput"));
  });
});

describe("the when column", () => {
  it("labels an outer run that never started with its creation", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "queued" });
    expect(cellOf("queued", "when").textContent).toBe("created 3h ago");
    expect(cellOf("queued", "when").getAttribute("title")).toBe(`created ${CREATED}`);
  });

  it("shows a started one's start, the time job:started sorts on", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "dates_grid" });
    expect(cellOf("dates_grid", "when").textContent).toBe("2h ago");
    expect(cellOf("dates_grid", "when").getAttribute("title")).toBe(`started ${STARTED}`);
  });
});
