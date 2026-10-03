import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../reports/AddToReport", () => ({
  default: ({ spec }: { spec: () => unknown }) => (
    <div data-testid="add-to-report" data-spec={JSON.stringify(spec())} />
  ),
}));
vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (a: string) => a.replaceAll("/", "-"),
}));
vi.mock("../../apiSeries", () => ({ fetchSeriesBatch: vi.fn(), fetchRunStatuses: vi.fn(() => Promise.resolve({})) }));
vi.mock("../../components/MetricBarChart", () => ({ default: () => null }));
vi.mock("../../components/OverlayChart", () => ({ default: () => null }));

import { api } from "../../api";
import { fetchSeriesBatch } from "../../apiSeries";
import LeaderboardCharts from "../LeaderboardCharts";
import Overlay from "../Overlay";
import Run from "../Run";

const spec = () => {
  const el = screen.queryByTestId("add-to-report");
  return el ? JSON.parse(el.getAttribute("data-spec")!) : null;
};
const at = (path: string, route: string, el: JSX.Element) => renderWithClient(
  <MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={el} /></Routes></MemoryRouter>,
);

beforeEach(() => vi.clearAllMocks());

describe("Add to report sources", () => {
  const charts = (view: "bar" | "trend") => renderWithClient(
    <MemoryRouter>
      <LeaderboardCharts view={view} onView={() => {}} rows={[{ verstr: "a" } as never]}
        metricCols={["loss"]} paramCols={[]} schema={null} onBrush={() => {}}
        importance={{ ws: "w", app: "my-app", filter: { query: "metrics.loss < 1" } }} />
    </MemoryRouter>,
  );

  it("leaderboard chart: the current view's spec", () => {
    charts("bar");
    expect(spec()).toMatchObject({ type: "bar", app: "my/app", metric: "loss", runs: { query: "metrics.loss < 1" } });
  });

  it("leaderboard trend: nothing to add", () => {
    charts("trend");
    expect(spec()).toBeNull();
  });

  it("overlay: curves of the shown runs and metrics", async () => {
    (fetchSeriesBatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      series: { a: { loss: [{ step: 0, value: 1, ts: null }, { step: 1, value: 0.5, ts: null }] } }, missing: [],
    });
    at("/ws/w/app/my-app/overlay?runs=a", "/ws/:ws/app/:app/overlay", <Overlay />);
    await waitFor(() => expect(spec()).toMatchObject({
      type: "curves", app: "my/app", runs: { verstrs: ["a"] }, keys: ["loss"], x: { mode: "step" }, smoothing: 0, log_y: false,
    }));
  });

  it("run page: the run panel", async () => {
    (api.experiment as ReturnType<typeof vi.fn>).mockResolvedValue({
      metadata: { verstr: "v1" }, metrics: {}, series: {}, log: [], patches: {},
    });
    (api.metricsSchema as ReturnType<typeof vi.fn>).mockResolvedValue({});
    at("/ws/w/app/my-app/run/v1", "/ws/:ws/app/:app/run/:verstr", <Run />);
    await waitFor(() => expect(spec()).toMatchObject({ type: "run", app: "my/app", runs: { verstrs: ["v1"] } }));
  });
});
