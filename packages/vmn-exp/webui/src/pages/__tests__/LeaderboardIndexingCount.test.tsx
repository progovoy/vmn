/** The All runs head while the store's index still loads: the snapshot's
 *  newest rows are not the store, so the count is of the store's runs. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const subtitle = () => document.querySelector(".page-sub")?.textContent ?? "";
const STATUS = {
  total: 500, failed_recent: 0, rollup: "stuck",
  counts: { created: 0, running: 0, stuck: 13, succeeded: 487, failed: 0 },
};
const trials = Array.from({ length: 4 }, (_, i) =>
  row(i + 1, { depth: 1, kind: "inner", parent: "0.0.999-dev.x" }));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(trials, 500));
});

describe("the All runs head while the index loads", () => {
  it("counts against the store's runs and says it is indexing", async () => {
    appStatus.mockResolvedValue({ ...STATUS, indexing: { loaded: 500, total: 709_603 } });
    renderBoard();
    await waitFor(() => expect(subtitle()).toBe("4 of 709,603 runs · indexing"));
  });

  it("counts the board's runs once the index has loaded", async () => {
    appStatus.mockResolvedValue(STATUS);
    renderBoard();
    await waitFor(() => expect(subtitle()).toBe("4 of 500 runs"));
  });
});
