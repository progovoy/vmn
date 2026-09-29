import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), experimentsPaged: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: () => "",
}));
vi.mock("../../apiSweep", () => ({ fetchSweep: vi.fn() }));

import { api } from "../../api";
import { fetchSweep } from "../../apiSweep";
import type { ExperimentDetail } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mockedSweep = fetchSweep as unknown as ReturnType<typeof vi.fn>;
const SPEC = { method: "grid", metric: { name: "loss", goal: "min" }, parameters: { x: { values: [1, 2] } } };
const SWEEP = "0.0.2-dev.aaa.bbb";

function detail(metadata: Record<string, unknown>): ExperimentDetail {
  return {
    metadata: { verstr: SWEEP, branch: "main", timestamp: "2026-01-01T12:00:00Z", ...metadata },
    metrics: {}, series: {}, patches: {},
    log: [{ timestamp: "2026-01-01T12:00:00Z", type: "create" }],
  };
}

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my_app/run/${SWEEP}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedSweep.mockResolvedValue({
    sweep: SWEEP, spec: SPEC,
    summary: { counts: { succeeded: 1 }, stopped_early: 0, trials: 1, best: null },
    trials: [{
      verstr: `${SWEEP}.r3`, name: "sw-t0", trial: 0, attempt: 0, status: "succeeded",
      params: { x: 1 }, value: 0.25, metric_source: `${SWEEP}.r4`, stopped_early: false,
    }],
  });
});

describe("Run page of a sweep", () => {
  it("shows the sweep section with the server's attributed trials", async () => {
    mockedApi.experiment.mockResolvedValue(detail({ sweep: SPEC }));
    renderRun();
    expect(await screen.findByTestId("sweep-spec")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId("sweep-trial")).toHaveLength(1));
    expect(mockedSweep).toHaveBeenCalledWith("test", "my_app", SWEEP);
    expect(mockedApi.experimentsPaged).not.toHaveBeenCalled();
    const link = screen.getByRole("link", { name: /leaderboard/i });
    expect(decodeURIComponent(link.getAttribute("href")!)).toBe(
      `/ws/test/app/my_app?q=parent = "${SWEEP}"`,
    );
  });

  it("has no sweep section for a plain run", async () => {
    mockedApi.experiment.mockResolvedValue(detail({}));
    renderRun();
    await screen.findByText("metadata");
    expect(screen.queryByTestId("sweep-spec")).not.toBeInTheDocument();
    expect(mockedSweep).not.toHaveBeenCalled();
  });
});
