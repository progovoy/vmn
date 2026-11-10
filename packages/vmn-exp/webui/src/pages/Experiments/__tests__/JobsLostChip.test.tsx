/** Plan 34 §3: lost is its own state. A **lost** chip beside **failed** keeps
 *  the outer runs with lost runs below them (`top_q=lost_below > 0`, URL
 *  `lost=1`), and an outer run whose only bad runs are lost reads its own
 *  status plus the count (`succeeded · 1 lost`). */
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
import { job, NO_COUNTS } from "../../../util/__tests__/jobFixture";
import { jobsPage, renderExperiments, topRow, urlParams } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = { branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, total: 900 };
const WITH_JOBS = { ...FACETS, parented: 800, jobs: 20, singles: 80 };
const STATUS = { total: 900, failed_recent: 0, rollup: null, counts: { created: 0, running: 0, stuck: 0, succeeded: 890, failed: 10 } };
const LAUNCH = topRow(36, {
  name: "launch", status: "succeeded", tree_status: "succeeded",
  job: job({ counts: { ...NO_COUNTS, succeeded: 19 }, lost: 1, done: 20, expected: 20, total: 20 }),
});
const lastOpts = () => m.experimentsPaged.mock.calls.slice(-1)[0][2];
const lostChip = () => screen.findByRole("button", { name: /^lost$/ });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.config.mockRejectedValue(new Error("nf"));
  m.facets.mockResolvedValue(WITH_JOBS);
  m.experimentsPaged.mockResolvedValue(jobsPage([LAUNCH], 1));
  appStatus.mockResolvedValue(STATUS);
});

describe("the lost chip", () => {
  it("keeps the outer runs with lost runs below them", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs");
    const chip = await lostChip();
    expect(chip.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(chip);
    await waitFor(() => expect(lastOpts().topQuery).toBe("lost_below > 0"));
    expect(urlParams().get("lost")).toBe("1");
  });

  it("travels in top_q beside the status chips", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs&status=failed&lost=1");
    const chip = await lostChip();
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(lastOpts().topQuery).toBe('tree_status = "failed" or lost_below > 0');
    fireEvent.click(chip);
    await waitFor(() => expect(lastOpts().topQuery).toBe('tree_status = "failed"'));
    expect(urlParams().get("lost")).toBeNull();
  });
});

describe("an outer run with lost runs", () => {
  it("reads its own status and the lost count", async () => {
    renderExperiments("/ws/test/app/my-app?kind=jobs");
    const name = await screen.findByRole("link", { name: "launch" });
    const pill = name.closest("tr")!.querySelector(".status-pill")!;
    expect(pill.textContent).toBe("succeeded · 1 lost");
  });
});
