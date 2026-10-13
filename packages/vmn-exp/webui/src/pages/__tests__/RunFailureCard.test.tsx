import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), meta: vi.fn(), experimentsDiff: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: () => "",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn() }));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));
vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));
vi.mock("../../components/TrainingCurves", () => ({ default: () => <div data-testid="training-curves" /> }));

import { api } from "../../api";
import { fetchRunBaselines } from "../../apiRunCode";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const RUN = "0.0.1-dev.bad";

function Where() {
  const { search, hash } = useLocation();
  return <output data-testid="where">{search}{hash}</output>;
}

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${RUN}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<><Run /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.meta.mockResolvedValue({ read_only: true });
  mockedApi.experimentsDiff.mockResolvedValue({ from_verstr: "v-good", to_verstr: RUN, metrics_delta: {}, diff: "" });
  (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
  mockedApi.experiment.mockResolvedValue({
    metadata: { verstr: RUN, timestamp: "2026-01-01T12:00:00Z", note: "" },
    metrics: {}, series: {}, log: [], patches: {},
    status: {
      status: "failed", exit_code: 1, started_at: null, finished_at: null, heartbeat: null,
      duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
      children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null,
    },
    artifacts: [{ name: "outputs/output.log", size: 4 }],
    output_tail: { lines: ["epoch 38", "CUDA out of memory"], truncated: false },
    last_step: { step: 38, of: 86 },
    last_good: { verstr: "v-good", idx: 41, name: "hist-000488" },
  });
});

describe("Run page failure card", () => {
  it("shows the detail's failure context", async () => {
    renderRun();
    await screen.findByTestId("training-curves");
    const card = document.querySelector(".run-error-card") as HTMLElement;
    expect(card.querySelector("pre.run-error-tail")?.textContent).toBe("epoch 38\nCUDA out of memory");
    expect(card.querySelector(".run-error-step")?.textContent).toBe("stopped at step 38 of 86");
    expect(card.querySelector(".run-error-since")?.textContent).toContain("@41 hist-000488");
  });

  it("sets the Changes baseline to the last good run", async () => {
    renderRun();
    await screen.findByTestId("training-curves");
    const card = document.querySelector(".run-error-card") as HTMLElement;
    fireEvent.click(card.querySelector(".run-error-since a") as HTMLElement);
    expect(screen.getByTestId("where").textContent).toBe("?baseline=v-good#changes");
    await waitFor(() => expect(mockedApi.experimentsDiff).toHaveBeenCalledWith("test", "my-app", "v-good", RUN));
  });
});
