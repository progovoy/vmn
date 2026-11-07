/** Plan 31 §1: the Outer runs failed chip's "≥ N% failed" option. A tree
 *  reads failed if any run in it failed; the option keeps the outer runs
 *  whose failure share is at least N (`top_q=failed_pct >= N`), N from the
 *  app's `experiment.ui.failed_pct_threshold` (default 5), kept in the URL
 *  as `failed_pct=N`. A filter, not a status. */
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
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
vi.mock("../../../apiBaseline", () => ({ baselineChips: vi.fn().mockResolvedValue({}) }));
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
import { jobsPage, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 900 };
const WITH_JOBS = { ...FACETS, parented: 800, jobs: 20, singles: 80 };
const STATUS = { total: 900, failed_recent: 0, rollup: null, counts: { created: 0, running: 0, stuck: 0, succeeded: 890, failed: 10 } };
const LAUNCH = topRow(36, { name: "launch" });
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];
const shareChip = (name: RegExp) => screen.findByRole("button", { name });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(new Error("nf"));
  m.facets.mockResolvedValue(WITH_JOBS);
  m.experimentsPaged.mockResolvedValue(jobsPage([LAUNCH], 1));
  appStatus.mockResolvedValue(STATUS);
});

describe("the failed chip's failure share", () => {
  it("is offered once failed is on, at the default 5%", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs&status=failed");
    const chip = await shareChip(/^≥ 5% failed$/);
    expect(chip.getAttribute("aria-pressed")).toBe("false");
    expect(lastOpts().topQuery).toBe('tree_status = "failed"');
    fireEvent.click(chip);
    await waitFor(() => expect(lastOpts().topQuery).toBe("failed_pct >= 5"));
    expect(urlParams().get("failed_pct")).toBe("5");
  });

  it("is not offered without the failed chip", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs&status=running");
    await screen.findByRole("link", { name: "launch" });
    expect(screen.queryByRole("button", { name: /% failed$/ })).toBeNull();
  });

  it("reads N from the URL, beside the other chips", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs&status=running,failed&failed_pct=12");
    const chip = await shareChip(/^≥ 12% failed$/);
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(lastOpts().topQuery).toBe('status = "running" or running_below > 0 or failed_pct >= 12');
    fireEvent.click(chip);
    await waitFor(() => expect(lastOpts().topQuery).toBe('status = "running" or running_below > 0 or tree_status = "failed"'));
    expect(urlParams().get("failed_pct")).toBeNull();
  });

  it("takes the app's threshold", async () => {
    appStatus.mockResolvedValue({ ...STATUS, failed_pct_threshold: 20 });
    renderExperiments("/ws/test/app/my-app?kind=jobs&status=failed");
    fireEvent.click(await shareChip(/^≥ 20% failed$/));
    await waitFor(() => expect(lastOpts().topQuery).toBe("failed_pct >= 20"));
  });
});
