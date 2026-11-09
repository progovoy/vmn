/** A metric whose steps went back without a rewind (`step_restarts`) is
 *  marked on the run page: its metric line and its chart. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), meta: vi.fn(), workspaces: vi.fn(), experimentsDiff: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (name: string) => name.replaceAll("/", "-"),
  artifactUrl: () => "",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn(), metricKeys: vi.fn() }));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));
vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));
vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { listComments: vi.fn(), reportsUsing: vi.fn() },
}));
vi.mock("../../components/TrainingCurves", () => ({
  default: ({ stepRestarts }: { stepRestarts?: unknown }) => (
    <div data-testid="curves-restarts">{JSON.stringify(stepRestarts ?? null)}</div>
  ),
}));

import { api } from "../../api";
import { apiReports } from "../../apiReports";
import { fetchRunBaselines } from "../../apiRunCode";
import { MetricsCard } from "../RunSections";
import { fullDetail, renderRunPage } from "./runPageFixture";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const reports = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;
const RESTART = { write: 122, from: 120, to: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("tail"))));
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.meta.mockResolvedValue({ read_only: true });
  mockedApi.workspaces.mockResolvedValue([]);
  (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
  reports.listComments.mockResolvedValue({ comments: [] });
  reports.reportsUsing.mockResolvedValue({ reports: [] });
});

describe("step counter restarts", () => {
  it("marks the metric line with where the steps went back", () => {
    render(
      <MetricsCard metrics={{ best: 0.989, loss: 0.2 }} schema={null} restarts={{ best: RESTART }} />,
    );
    const mark = screen.getByTestId("metric-restart-best");
    expect(mark.textContent).toBe("step counter restarted");
    expect(mark.getAttribute("title")).toBe("steps went back from 120 to 0 at write 122");
    expect(screen.queryByTestId("metric-restart-loss")).toBeNull();
  });

  it("passes the detail's restarts to the metric card and the charts", async () => {
    mockedApi.experiment.mockResolvedValue(fullDetail({
      metrics: { best: 0.989 }, step_restarts: { best: RESTART },
    }));
    renderRunPage();
    expect((await screen.findByTestId("metric-restart-best")).textContent).toBe("step counter restarted");
    expect(JSON.parse(screen.getByTestId("curves-restarts").textContent!)).toEqual({ best: RESTART });
  });
});
