import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), experimentsPaged: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: () => "",
}));

import { api } from "../../api";
import type { ExperimentDetail } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
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
  mockedApi.experimentsPaged.mockResolvedValue({
    rows: [{
      idx: 3, verstr: `${SWEEP}.r3`, code_verstr: SWEEP, timestamp: null, note: null,
      branch: null, base_version: null, user_meta: null, name: "sw-t0", status: "succeeded",
      params: { x: 1 }, metrics: { loss: 0.25 }, tags: { sweep_trial: "0", sweep_attempt: "0" },
    }],
    total: 1,
  });
});

describe("Run page of a sweep", () => {
  it("shows the sweep section with the sweep's trials", async () => {
    mockedApi.experiment.mockResolvedValue(detail({
      sweep: { method: "grid", metric: { name: "loss", goal: "min" }, parameters: { x: { values: [1, 2] } } },
    }));
    renderRun();
    expect(await screen.findByTestId("sweep-spec")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId("sweep-trial")).toHaveLength(1));
    const [, , opts] = mockedApi.experimentsPaged.mock.calls[0];
    expect(opts.query).toBe(`parent = "${SWEEP}"`);
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
    expect(mockedApi.experimentsPaged).not.toHaveBeenCalled();
  });
});
