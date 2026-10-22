/** A slow or failing request never leaves the board showing another view's
 *  rows: switching Outer runs -> Single runs shows loading, a filter change
 *  keeps the old rows marked stale, and a server error is said even then. */
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
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = {
  branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {},
  total: 3_053, parented: 0, jobs: 3, singles: 3_050,
};
const JOBS = [topRow(1, { name: "job_a" }), topRow(2, { name: "job_b" }), topRow(3, { name: "job_c" })];
const never = () => new Promise(() => {});
const switcher = () => screen.getByRole("group", { name: "Experiments view" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(notFound());
  m.facets.mockResolvedValue(FACETS);
  m.experimentsPaged.mockResolvedValue(jobsPage(JOBS));
});

describe("a slow board request", () => {
  it("switching to the single runs never shows the outer runs' rows", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "job_a" });
    m.experimentsPaged.mockReturnValue(never());
    fireEvent.click(within(switcher()).getByRole("button", { name: /^Single runs/ }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "job_a" })).toBeNull());
    expect(screen.queryByText("3 single runs")).toBeNull();
    expect(screen.getByText("loading single runs…")).toBeInTheDocument();
  });

  it("a filter change keeps the old rows, marked as updating", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })], 3_050));
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await screen.findByRole("link", { name: "solo" });
    m.experimentsPaged.mockReturnValue(never());
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByText("updating…")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "solo" }).closest("[aria-busy='true']")).not.toBeNull();
  });

  it("a server error on the new request is shown over the stale rows", async () => {
    m.experimentsPaged.mockResolvedValue(jobsPage([singleRow(1, { name: "solo" })], 3_050));
    renderExperiments("/ws/test/app/my-app?kind=singles");
    await screen.findByRole("link", { name: "solo" });
    m.experimentsPaged.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
  });
});
