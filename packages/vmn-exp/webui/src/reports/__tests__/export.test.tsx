import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { renderWithClient } from "../../test-utils";

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => ({
    default: (p: Record<string, unknown>) => <div data-testid={name} data-props={JSON.stringify(p)} />,
  }),
}));
vi.mock("../../components/LazyMount", () => ({ default: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("../../components/OverlayChart", () => stub("OverlayChart"));
vi.mock("../../components/MetricBarChart", () => stub("MetricBarChart"));
vi.mock("../../components/MetricScatter", () => stub("MetricScatter"));
vi.mock("../../components/ParallelCoordinates", () => stub("ParallelCoordinates"));
vi.mock("../../components/ParamImportance", () => stub("ParamImportance"));
vi.mock("../../components/GroupedMetrics", () => stub("GroupedMetrics"));
vi.mock("../../components/MediaTable", () => stub("MediaTable"));
vi.mock("../../components/RunHistograms", () => stub("RunHistograms"));
vi.mock("../../components/MediaImages", () => ({
  default: ({ media, url }: { media: Record<string, { path: string }[]>; url: (p: string) => string }) => (
    <div data-testid="MediaImages">
      {Object.values(media).flat().map((i) => <img key={i.path} alt={i.path} src={url(i.path)} />)}
    </div>
  ),
}));
vi.mock("../../components/RunLineage", () => ({
  LineageView: () => <div data-testid="LineageView" />,
}));
vi.mock("../../api", () => ({
  api: { experimentsColumns: vi.fn(), experimentsPaged: vi.fn(), experiment: vi.fn(), metricsSchema: vi.fn() },
  appTag: (a: string) => a.replaceAll("/", "-"),
  artifactUrl: () => "/api/never",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn() }));

import { api } from "../../api";
import { runLineage } from "../../apiRun";
import Panel from "../Panel";
import { PanelCaptureProvider, usePanelCapture, type PanelCapture, type PanelPayload } from "../publishedData";
import { ExportedReport, mountExport, type ExportData } from "../export";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mLineage = runLineage as unknown as ReturnType<typeof vi.fn>;

const COLUMNS = {
  verstrs: ["a", "b"], idx: [1, 2],
  columns: { "metrics.loss": [0.5, 0.3], "params.lr": [0.1, 0.01] },
};
const DETAIL = {
  metadata: { verstr: "a" }, metrics: { loss: 0.5, acc: 0.9 }, params: { lr: 0.1 },
  series: {}, patches: {}, status: { status: "succeeded", exit_code: 0 },
  media: { img: [{ step: 1, path: "media/img/1.png" }] },
  tables: { preds: [{ step: 1, path: "tables/preds/1.json" }] },
  histograms_total: { grads: 3 }, histograms: { grads: [] },
};
const query = { query: "metrics.loss < 1" };
const one = { verstrs: ["a"] };
const SPECS: Record<string, Record<string, unknown>> = {
  curves: { runs: query, keys: ["loss"] },
  leaderboard: { runs: query, columns: ["loss"] },
  bar: { runs: query, metric: "loss" },
  scatter: { runs: query, x: "params.lr", y: "loss" },
  parallel: { runs: query, columns: ["params.lr", "loss"] },
  importance: { runs: query, metric: "loss" },
  grouped: { runs: query, group_by: "params.lr", metric: "loss" },
  media: { runs: one, key: "img" },
  table: { runs: one, path: "tables/preds/1.json" },
  histogram: { runs: one, key: "grads" },
  lineage: { runs: one },
  run: { runs: one },
};
const spec = (type: string) => ({ v: 1, id: `p-${type}`, app: "my_app", type, ...SPECS[type] });
const IMG = "data:image/png;base64,iVBORw0K";

let capture: PanelCapture | null = null;
function Grab() {
  capture = usePanelCapture();
  return null;
}

function mockLive() {
  m.experimentsColumns.mockResolvedValue(COLUMNS);
  m.experimentsPaged.mockResolvedValue({
    rows: [{ idx: 1, verstr: "a", metrics: { loss: 0.5 }, params: { lr: 0.1 } },
      { idx: 2, verstr: "b", metrics: { loss: 0.3 }, params: { lr: 0.01 } }],
    total: 2,
  });
  m.experiment.mockResolvedValue(DETAIL);
  m.metricsSchema.mockResolvedValue({ metrics: {} });
  mLineage.mockResolvedValue({ root: { verstr: "a" }, upstream: [], downstream: [] });
}

async function publishAll(): Promise<Record<string, PanelPayload>> {
  mockLive();
  const view = renderWithClient(
    <MemoryRouter>
      <PanelCaptureProvider>
        <Grab />
        {Object.keys(SPECS).map((t) => <Panel key={t} ws="w" spec={spec(t)} />)}
      </PanelCaptureProvider>
    </MemoryRouter>,
  );
  const fetching = Object.keys(SPECS).filter((t) => t !== "curves" || !("verstrs" in (SPECS[t].runs as object)));
  await waitFor(() => expect(Object.keys(capture!.collect()).sort()).toEqual(fetching.map((t) => `p-${t}`).sort()));
  await screen.findByTestId("LineageView");
  const data = JSON.parse(JSON.stringify(capture!.collect()));
  view.unmount();
  return data;
}

const block = (s: Record<string, unknown>) => "```vmn-panel\n" + JSON.stringify(s) + "\n```\n\n";
const exportData = (panels: Record<string, PanelPayload>): ExportData => ({
  title: "Sweep summary", rev: 2,
  body: "# Sweep summary\n\n" + Object.keys(SPECS).map((t) => block(spec(t))).join("") + "tail\n",
  panels, media: { "vmn://my_app/a/media/img/1.png": IMG },
});

beforeEach(() => {
  vi.clearAllMocks();
  capture = null;
});

describe("exported report", () => {
  it("captures the workspace each panel fetched from", async () => {
    const panels = await publishAll();
    expect(panels["p-run"].ws).toBe("w");
  });

  it("renders every panel type from inlined data without any fetch", async () => {
    const panels = await publishAll();
    vi.clearAllMocks();
    for (const fn of [...Object.values(m), mLineage]) fn.mockRejectedValue(new Error("network"));
    render(<ExportedReport data={exportData(panels)} />);
    expect(screen.getByRole("heading", { name: "Sweep summary" })).toBeInTheDocument();
    for (const id of ["OverlayChart", "MetricBarChart", "MetricScatter", "ParallelCoordinates", "ParamImportance",
      "GroupedMetrics", "MediaTable", "RunHistograms", "LineageView", "MediaImages"]) {
      expect(await screen.findByTestId(id)).toBeInTheDocument();
    }
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("acc")).toBeInTheDocument();
    expect(screen.getByAltText("media/img/1.png")).toHaveAttribute("src", IMG);
    expect(screen.getByText("tail")).toBeInTheDocument();
    for (const fn of [...Object.values(m), mLineage]) expect(fn).not.toHaveBeenCalled();
  });

  it("an image over the media cap renders without a source", async () => {
    const panels = await publishAll();
    render(<ExportedReport data={{ ...exportData(panels), media: {} }} />);
    expect(await screen.findByAltText("media/img/1.png")).not.toHaveAttribute("src", expect.stringMatching(/api/));
  });

  it("a panel without published data says so", () => {
    render(<ExportedReport data={{ ...exportData({}), body: block(spec("run")) }} />);
    expect(screen.getByText("No published data for this panel")).toBeInTheDocument();
  });

  it("mounts from the data script of the page", () => {
    document.body.innerHTML = '<div id="root"></div><script type="application/json" id="vmn-report-data"></script>';
    const data = { ...exportData({}), body: "# Hello export\n" };
    document.getElementById("vmn-report-data")!.textContent = JSON.stringify(data);
    mountExport(document);
    return waitFor(() => expect(screen.getByRole("heading", { name: "Hello export" })).toBeInTheDocument());
  });
});
