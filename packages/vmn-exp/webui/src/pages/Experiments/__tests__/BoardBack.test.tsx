/** Back to a board seen before paints its cached rows at once, marked as
 *  updating, even while the revalidation never answers (production: the
 *  browser's 6 connections were all held elsewhere). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen } from "@testing-library/react";

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
import { jobsPage, nav, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const never = () => new Promise<never>(() => {});
const FACETS = {
  branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {},
  total: 3, parented: 0, jobs: 1, singles: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(FACETS);
  m.experimentsColumns.mockImplementation(never);
  m.experiments.mockResolvedValue(Object.assign([singleRow(1, { name: "solo" })], { total: 1 }));
  m.experimentsPaged.mockResolvedValue(jobsPage([topRow(1, { name: "job_a" }), singleRow(2, { name: "solo" })]));
});

async function goAndBack(name: string) {
  fireEvent.click(await screen.findByRole("link", { name }));
  expect(await screen.findByText("run page")).toBeInTheDocument();
  m.experimentsPaged.mockImplementation(never);
  m.experiments.mockImplementation(never);
  await act(async () => { nav.back(); });
}

describe("back to a board", () => {
  it("the Outer runs view paints its cached rows at once, marked as updating", async () => {
    renderExperiments();
    await goAndBack("job_a");
    expect(screen.getByRole("link", { name: "job_a" })).toBeInTheDocument();
    expect(screen.queryByText(/^loading/)).toBeNull();
    expect(screen.getByText("updating…")).toBeInTheDocument();
  });

  it("the All runs board paints its cached rows at once, marked as updating", async () => {
    renderExperiments("/ws/test/app/my-app?view=all");
    await goAndBack("solo");
    expect(screen.getByRole("link", { name: "solo" })).toBeInTheDocument();
    expect(screen.queryByText("loading runs…")).toBeNull();
    expect(screen.getByText("updating…")).toBeInTheDocument();
  });

  it("a filter whose answer never came paints the view's last rows on Back, marked as updating", async () => {
    renderExperiments("/ws/test/app/my-app?view=all");
    await screen.findByRole("link", { name: "solo" });
    m.experimentsPaged.mockImplementation(never);
    m.experiments.mockImplementation(never);
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByText("updating…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "solo" }));
    expect(await screen.findByText("run page")).toBeInTheDocument();
    await act(async () => { nav.back(); });
    expect(screen.getByRole("link", { name: "solo" })).toBeInTheDocument();
    expect(screen.queryByText("loading runs…")).toBeNull();
    expect(screen.getByText("updating…")).toBeInTheDocument();
  });
});
