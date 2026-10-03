import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => ({
    default: (p: Record<string, unknown>) => <div data-testid={name} data-props={JSON.stringify(p)} />,
  }),
}));
vi.mock("../../components/OverlayChart", () => stub("OverlayChart"));
vi.mock("../../components/MetricBarChart", () => stub("MetricBarChart"));
vi.mock("../../components/MetricScatter", () => stub("MetricScatter"));
vi.mock("../../components/ParallelCoordinates", () => stub("ParallelCoordinates"));
vi.mock("../../components/ParamImportance", () => stub("ParamImportance"));
vi.mock("../../components/GroupedMetrics", () => stub("GroupedMetrics"));
vi.mock("../../api", () => ({
  api: { experimentsColumns: vi.fn(), experimentsPaged: vi.fn(), experiment: vi.fn(), metricsSchema: vi.fn() },
  appTag: (a: string) => a.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
  artifactUrl: () => "/x",
}));

import { api } from "../../api";
import Panel from "../Panel";
import { leaderboardSpec, overlaySpec, runSpec } from "../viewSpecs";
import { validate } from "../panelSpec";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const props = (id: string) => JSON.parse(screen.getByTestId(id).getAttribute("data-props")!);
const render = (spec: unknown) => renderWithClient(<MemoryRouter><Panel ws="w" spec={spec} /></MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentsColumns.mockResolvedValue({ verstrs: ["a"], idx: [1], columns: { "metrics.loss": [0.5] } });
  m.experimentsPaged.mockResolvedValue({ rows: [{ idx: 1, verstr: "a", metrics: { loss: 0.5 }, params: {} }], total: 1 });
  m.experiment.mockResolvedValue({ metadata: { verstr: "a" }, metrics: {}, params: {}, series: {}, patches: {}, status: {} });
  m.metricsSchema.mockResolvedValue({ metrics: {} });
});

const board = {
  app: "root-svc", filter: { query: "metrics.loss < 1", sort: "loss", order: "asc" as const },
  verstrs: ["a"], metricCols: ["loss", "acc"], paramCols: ["lr"], defaultMetric: "acc",
};

describe("view specs", () => {
  it.each([
    ["bar", "MetricBarChart", { metricCols: ["loss"] }],
    ["scatter", "MetricScatter", { initialX: "loss", initialY: "acc" }],
    ["parallel", "ParallelCoordinates", { metricCols: ["loss", "acc"], paramCols: ["lr"] }],
    ["grouped", "GroupedMetrics", { metricCols: ["loss"], initialGroup: "branch" }],
    ["importance", "ParamImportance", { defaultMetric: "acc" }],
  ] as const)("leaderboard %s renders the same chart", async (view, comp, expected) => {
    const spec = leaderboardSpec({ ...board, view })!;
    expect(validate(spec).ok).toBe(true);
    expect(spec.app).toBe("root/svc");
    expect(spec.runs).toEqual({ query: "metrics.loss < 1", sort: "loss", order: "asc" });
    render(spec);
    await waitFor(() => expect(props(comp).rows).toHaveLength(1));
    expect(props(comp)).toMatchObject(expected);
  });

  it("leaderboard without a query pins the plotted runs", () => {
    expect(leaderboardSpec({ ...board, filter: {}, view: "bar" })!.runs).toEqual({ verstrs: ["a"] });
  });

  it("trend has no panel equivalent", () => {
    expect(leaderboardSpec({ ...board, view: "trend" })).toBeNull();
  });

  it("overlay renders the same curves", () => {
    const view = { app: "my_app", verstrs: ["a", "b"], keys: ["loss"], smoothing: 0.3, xMode: "step" as const, x: "epoch", logY: true };
    const spec = overlaySpec(view);
    expect(validate(spec).ok).toBe(true);
    render(spec);
    expect(props("OverlayChart")).toMatchObject({
      app: "my_app", verstrs: ["a", "b"], keys: ["loss"], smoothing: 0.3, xMode: "step", x: "epoch", logY: true,
    });
  });

  it("overlay with auto x keeps the x mode", () => {
    const spec = overlaySpec({ app: "a", verstrs: ["a"], keys: ["l"], smoothing: 0, xMode: "wall", x: "auto", logY: false });
    render(spec);
    expect(props("OverlayChart")).toMatchObject({ xMode: "wall", x: "auto" });
  });

  it("run page pins its run", () => {
    const spec = runSpec("root-svc", "1.0.0-dev.1");
    expect(spec).toMatchObject({ type: "run", app: "root/svc", runs: { verstrs: ["1.0.0-dev.1"] } });
    expect(validate(spec).ok).toBe(true);
  });
});
