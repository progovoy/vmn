/** Plan 28 N3 on the Outer runs view: each outer run's baseline chip beside
 *  its name, the chips of a page's outer runs fetched in one request. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../apiShell", () => ({ apiShell: { appStatus: () => new Promise(() => {}) } }));
vi.mock("../../../apiBaseline", () => ({ baselineChips: vi.fn() }));
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
import { baselineChips } from "../../../apiBaseline";
import { CHIP, REF } from "../../../components/__tests__/baselineFixture";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const LAUNCH = topRow(36, { name: "launch" });
const FIRST = topRow(35, { name: "first" });
const nameCell = (name: string) =>
  screen.getByRole("link", { name }).closest("tr")!.querySelector('[data-col-id="name"]')! as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ best_value: { goal: "max" } });
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([LAUNCH, FIRST, singleRow(34, { name: "solo" })]));
  vi.mocked(baselineChips).mockResolvedValue({
    [LAUNCH.verstr]: { ...CHIP, baseline: REF }, [FIRST.verstr]: null,
  });
});

describe("an outer run's baseline chip", () => {
  it("shows beside its name, linking to its Overview", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "launch" });
    const chip = await within(nameCell("launch")).findByText(/▼ best_value from 2024-12/);
    expect(chip).toHaveClass("baseline-worse");
    expect(chip.closest("a")).toHaveAttribute("href", `/ws/test/app/my-app/run/${LAUNCH.verstr}?tab=overview`);
    expect(nameCell("first").querySelector(".baseline-chip")).toBeNull();
  });

  it("is fetched for the page's outer runs in one request, single runs left out", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "launch" });
    await waitFor(() => expect(baselineChips).toHaveBeenCalled());
    expect(baselineChips).toHaveBeenCalledTimes(1);
    expect(baselineChips).toHaveBeenCalledWith("test", "my-app", [LAUNCH.verstr, FIRST.verstr]);
  });
});
