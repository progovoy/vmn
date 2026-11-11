/** The view switch's counts follow the view's filters: unfiltered they are
 *  the facets' (every outer run, every single run); with a filter (`q`,
 *  status, a search, a preset) the shown side counts what its board
 *  answered, and the other side, not asked under those filters, shows no
 *  number rather than the app's whole count. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";

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
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 9_000 };
const WITH_JOBS = { ...FACETS, parented: 8_000, jobs: 44, singles: 950 };
const options = () =>
  within(screen.getByRole("group", { name: "Experiments view" })).getAllByRole("button").map((b) => b.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(WITH_JOBS);
  m.experimentsPaged.mockResolvedValue(jobsPage([topRow(2, { name: "grid" })], 14));
});

describe("the view switch's counts", () => {
  it("count the outer runs a q matches on the shown side, no number on the other", async () => {
    renderExperiments("/ws/test/app/my-app?q=tags.target%20%3D%20%22a%22");
    await screen.findByRole("link", { name: "grid" });
    expect(await screen.findByText("14 outer runs")).toBeInTheDocument();
    expect(options()).toEqual(["Outer runs (14)", "Single runs", "All runs"]);
  });

  it("count the single runs a status matches when they are shown", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })], 7));
    renderExperiments("/ws/test/app/my-app?kind=singles&status=failed");
    await screen.findByRole("link", { name: "solo" });
    expect(options()).toEqual(["Outer runs", "Single runs (7)", "All runs"]);
  });

  it("stay the facets' without a filter", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(options()).toEqual(["Outer runs (44)", "Single runs (950)", "All runs"]);
  });
});
