/** The Outer runs view over an answer still indexing (plan 33 §2.2) says so
 *  from the answer itself, whatever the status poll says. */
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
  total: 0, failed_recent: 0, rollup: null,
  counts: { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0 },
};
const INDEXING = { loaded: 120_000, total: 734_000 };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  appStatus.mockResolvedValue(STATUS);
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue({ ...jobsPage([]), indexing: INDEXING });
});

describe("the Outer runs view over an answer still indexing", () => {
  it("says the results are incomplete, not that the app has none", async () => {
    const { container } = renderExperiments();
    await waitFor(() => expect(screen.getByText(/Loading runs from the store/)).toBeInTheDocument());
    expect(screen.queryByText(/No runs yet/)).not.toBeInTheDocument();
    expect(container.querySelector(".board-count")?.textContent)
      .toBe("0 runs so far · indexing 16% — results incomplete");
  });
});
