import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiments: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: vi.fn() } }));
vi.mock("../../components/ParamPlots", () => ({ default: () => <div /> }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { apiShell } from "../../apiShell";
import Leaderboard from "../Experiments/AllRunsView";

const mocked = {
  experiments: api.experiments as unknown as ReturnType<typeof vi.fn>,
  metricsSchema: api.metricsSchema as unknown as ReturnType<typeof vi.fn>,
  appStatus: apiShell.appStatus as unknown as ReturnType<typeof vi.fn>,
};

function renderBoard() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const STATUS = {
  total: 0, failed_recent: 0, rollup: null,
  counts: { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0 },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.experiments.mockResolvedValue([]);
  mocked.metricsSchema.mockResolvedValue({});
});

describe("an empty board while the store's index loads", () => {
  it("says the runs are loading, not that the app has none", async () => {
    mocked.appStatus.mockResolvedValue({ ...STATUS, indexing: { loaded: 12_000, total: 667_794 } });
    renderBoard();
    await waitFor(() => expect(screen.getByText(/Loading runs from the store/)).toBeInTheDocument());
    expect(screen.getByText(/12,000 \/ 667,794 runs/)).toBeInTheDocument();
    expect(screen.queryByText(/No runs yet in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/vmn-exp create/)).not.toBeInTheDocument();
  });

  it("still offers vmn-exp create once the index has loaded and holds none", async () => {
    mocked.appStatus.mockResolvedValue(STATUS);
    renderBoard();
    await waitFor(() => expect(screen.getByText(/No runs yet in/)).toBeInTheDocument());
  });
});
