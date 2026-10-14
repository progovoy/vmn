/** The job Charts tab reads up to 50k runs' columns: it refetches them once
 *  about 5% more of the job is done (and once it is all done), not on
 *  every finished run. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { createQueryClient } from "../../../queryClient";

vi.mock("uplot", async () => await import("../../../components/__tests__/fakeUPlot"));
vi.mock("../../../apiJobCharts", () => ({ jobFacets: vi.fn(), jobColumns: vi.fn(), jobTopRuns: vi.fn() }));
vi.mock("../../../components/OverlayChart", () => ({ default: () => null }));

import { jobColumns, jobFacets, jobTopRuns } from "../../../apiJobCharts";
import { enableCanvas, resetInstances } from "../../../components/__tests__/fakeUPlot";
import type { JobSummary } from "../../../apiJob";
import type { ExperimentColumns } from "../../../types";
import JobCharts from "../JobCharts";
import { JOB, jobSummaryFixture } from "./jobFixture";

const columns = (keys: string[]): ExperimentColumns => ({
  verstrs: ["r1", "r2"], idx: [1, 2], total: 2,
  columns: Object.fromEntries(keys.map((k) => [k, k === "params.lr" ? [0.1, 0.01] : [0.5, 0.3]])),
});

beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  vi.mocked(jobFacets).mockResolvedValue({
    branches: ["main"], metric_keys: ["val_loss"], param_keys: ["lr"], tag_keys: [],
    param_values: { lr: 2 }, parented: 2, jobs: 0, singles: 0, total: 2,
  });
  vi.mocked(jobColumns).mockImplementation(async (_ws, _app, _v, keys) => columns(keys));
  vi.mocked(jobTopRuns).mockResolvedValue([]);
});

function mount() {
  const client = createQueryClient();
  const ui = (summary: JobSummary) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}?tab=charts`]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<JobCharts ws="test" app="my-app" summary={summary} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const utils = render(ui(jobSummaryFixture({ done: 1412, expected: 2000 })));
  return (done: number) => utils.rerender(ui(jobSummaryFixture({ done, expected: 2000 })));
}

describe("the job Charts tab's refetches", () => {
  it("waits for about 5% more of the job before reading its columns again", async () => {
    const setDone = mount();
    await screen.findByRole("figure", { name: /val_loss against lr/ });
    expect(jobColumns).toHaveBeenCalledTimes(1);
    setDone(1413);
    setDone(1450);
    await new Promise((r) => setTimeout(r, 20));
    expect(jobColumns).toHaveBeenCalledTimes(1);
    setDone(1500);
    await waitFor(() => expect(jobColumns).toHaveBeenCalledTimes(2));
    setDone(2000);
    await waitFor(() => expect(jobColumns).toHaveBeenCalledTimes(3));
  });
});
