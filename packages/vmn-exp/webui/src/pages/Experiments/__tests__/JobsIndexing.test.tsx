/** The Outer runs view while the store's index still loads: the newest rows
 *  so far may hold no top-level run, which is no empty app. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";

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
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../../api";
import { jobsPage, notFound, renderExperiments } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const STATUS = {
  total: 500, failed_recent: 0, rollup: "stuck",
  counts: { created: 0, running: 0, stuck: 13, succeeded: 487, failed: 0 },
};
const INDEXING = { ...STATUS, indexing: { loaded: 500, total: 709_603 } };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([]));
});

describe("the Outer runs view while the index loads", () => {
  it("says the runs are loading, not that the app has none", async () => {
    appStatus.mockResolvedValue(INDEXING);
    renderExperiments();
    await waitFor(() => expect(screen.getByText(/Loading runs from the store/)).toBeInTheDocument());
    expect(screen.queryByText(/No runs yet/)).not.toBeInTheDocument();
    expect(screen.queryByText(/vmn-exp create/)).not.toBeInTheDocument();
  });

  it("counts the top-level runs as so far", async () => {
    appStatus.mockResolvedValue(INDEXING);
    const { container } = renderExperiments();
    await waitFor(() => expect(container.querySelector(".board-count")?.textContent)
      .toBe("0 runs so far · indexing 500 / 709,603 runs"));
  });

  it("still offers vmn-exp create once the index has loaded and holds none", async () => {
    appStatus.mockResolvedValue({ ...STATUS, total: 0, counts: { ...STATUS.counts, stuck: 0 } });
    const { container } = renderExperiments();
    await waitFor(() => expect(screen.getByText(/No runs yet/)).toBeInTheDocument());
    expect(container.querySelector(".board-count")?.textContent).toBe("0 runs");
  });
});
