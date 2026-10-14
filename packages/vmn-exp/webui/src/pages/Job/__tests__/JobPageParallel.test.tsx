/** Opened from a board that already lists the run as a job, the job page
 *  asks for its summary alongside the detail, not after it. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../../api", () => ({
  api: { experiment: vi.fn(), experiments: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));

import { api } from "../../../api";
import { jobSummary } from "../../../apiJob";
import { rowsKey } from "../../../queries";
import { createQueryClient } from "../../../queryClient";
import type { ExperimentRow } from "../../../types";
import Run from "../../Run";
import { JOB, jobSummaryFixture } from "./jobFixture";

const m = api as unknown as Record<"experiment" | "experiments" | "metricsSchema", ReturnType<typeof vi.fn>>;
const row = (extra: Partial<ExperimentRow>): ExperimentRow => ({
  idx: 36, verstr: JOB, code_verstr: "0.0.2", timestamp: null, note: null, branch: "main",
  base_version: "0.0.1", params: {}, metrics: {}, ...extra,
});

function renderRun(cached: ExperimentRow) {
  const client = createQueryClient();
  client.setQueryData(rowsKey("test", "my-app", { sort: "idx" }), { rows: [cached], total: 1 });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}`]}>
        <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.experiments.mockResolvedValue([]);
  m.experiment.mockReturnValue(new Promise(() => {})); // the detail never lands
  vi.mocked(jobSummary).mockResolvedValue(jobSummaryFixture());
});

describe("the job page's first requests", () => {
  it("asks for a listed job's summary before its detail lands", async () => {
    renderRun(row({ kind: "outer", children: ["k1"] }));
    await waitFor(() => expect(jobSummary).toHaveBeenCalledWith("test", "my-app", JOB));
  });

  it("waits for the detail when the listed run is a single one", async () => {
    renderRun(row({ kind: "single" }));
    await waitFor(() => expect(m.experiment).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(jobSummary).not.toHaveBeenCalled();
  });
});
