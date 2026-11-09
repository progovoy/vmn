/** The All runs board over an index still loading says so from its own
 *  answer's `indexing` (plan 33 §2.2), not only from the status poll: an
 *  upgrade's re-derive serves a partial board the status may not know of yet. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const subtitle = () => document.querySelector(".page-sub")?.textContent ?? "";
const STATUS = {
  total: 4, failed_recent: 0, rollup: null,
  counts: { created: 0, running: 0, stuck: 0, succeeded: 4, failed: 0 },
};
const INDEXING = { loaded: 120_000, total: 734_000 };
const INCOMPLETE = "indexing 16% — results incomplete";
const rows = Array.from({ length: 4 }, (_, i) => row(i + 1));
const notFound = () => Object.assign(new Error("nf"), { status: 404 });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  appStatus.mockResolvedValue(STATUS);
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsColumns.mockRejectedValue(notFound());
});

describe("the All runs board over an answer still indexing", () => {
  it("counts against the store's runs and says the results are incomplete", async () => {
    m.experiments.mockResolvedValue(Object.assign(page(rows, 4), { indexing: INDEXING }));
    renderBoard();
    await waitFor(() => expect(subtitle()).toBe(`4 of 734,000 runs · ${INCOMPLETE}`));
  });

  it("an empty answer still indexing is no empty app", async () => {
    m.experiments.mockResolvedValue(Object.assign(page([], 0), { indexing: INDEXING }));
    renderBoard();
    await waitFor(() => expect(screen.getByText(/Loading runs from the store/)).toBeInTheDocument());
    expect(screen.queryByText(/No runs yet in/)).not.toBeInTheDocument();
  });

  it("a grouped answer says so too", async () => {
    m.experimentGroups.mockResolvedValue({
      groups: [{
        key: "main", label: "main", target: null, aggregates: {}, rows, rows_total: 4,
        counts: { total: 4, running: 0, waiting: 0, done: 4, failed: 0, stuck: 0 },
      }],
      total_groups: 1, total_rows: 4, aggregate: "mean", running: 0, metric: null, goal: null,
      indexing: INDEXING,
    });
    renderBoard("/ws/test/app/my-app?group=branch");
    await waitFor(() => expect(subtitle()).toContain(INCOMPLETE));
  });

  it("an answer over a loaded index says nothing of indexing", async () => {
    m.experiments.mockResolvedValue(page(rows, 4));
    renderBoard();
    await waitFor(() => expect(subtitle()).toBe("4 runs"));
  });
});
