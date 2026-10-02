import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { renderWithClient } from "../../test-utils";

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => ({
    default: (p: Record<string, unknown>) => (
      <div data-testid={name} data-props={JSON.stringify(p, (k, v) => (k === "url" ? undefined : v))} />
    ),
  }),
}));
vi.mock("../../components/OverlayChart", () => stub("OverlayChart"));
vi.mock("../../components/MetricBarChart", () => stub("MetricBarChart"));
vi.mock("../../components/MetricScatter", () => stub("MetricScatter"));
vi.mock("../../components/ParallelCoordinates", () => stub("ParallelCoordinates"));
vi.mock("../../components/ParamImportance", () => stub("ParamImportance"));
vi.mock("../../components/GroupedMetrics", () => stub("GroupedMetrics"));
vi.mock("../../components/MediaImages", () => stub("MediaImages"));
vi.mock("../../components/MediaTable", () => stub("MediaTable"));
vi.mock("../../components/RunHistograms", () => stub("RunHistograms"));
vi.mock("../../components/RunLineage", () => ({
  LineageView: (p: Record<string, unknown>) => <div data-testid="LineageView" data-props={JSON.stringify(p)} />,
}));
vi.mock("../../api", () => ({
  api: {
    experimentsColumns: vi.fn(),
    experimentsPaged: vi.fn(),
    experiment: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appTag: (a: string) => a.replaceAll("/", "-"),
  artifactUrl: () => "/x",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn() }));

import { api } from "../../api";
import { runLineage } from "../../apiRun";
import Panel from "../Panel";
import { Markdown } from "../Markdown";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mLineage = runLineage as unknown as ReturnType<typeof vi.fn>;

const COLUMNS = {
  verstrs: ["a", "b"], idx: [1, 2],
  columns: { "metrics.loss": [0.5, 0.3], "params.lr": [0.1, 0.01], branch: ["main", "dev"] },
};
const DETAIL = {
  metadata: { verstr: "a" }, metrics: { loss: 0.5, acc: 0.9 }, params: { lr: 0.1 },
  series: {}, patches: {}, status: { status: "succeeded", exit_code: 0, duration_sec: 12 },
  media: { img: [{ step: 1, path: "media/img/1.png" }], other: [] },
  tables: { preds: [{ step: 1, path: "tables/preds/1.json" }], other: [] },
  histograms_total: { grads: 3, other: 1 }, histograms: { grads: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentsColumns.mockResolvedValue(COLUMNS);
  m.experimentsPaged.mockResolvedValue({
    rows: [{ idx: 1, verstr: "a", metrics: { loss: 0.5 }, params: { lr: 0.1 } },
      { idx: 2, verstr: "b", metrics: { loss: 0.3 }, params: { lr: 0.01 } }],
    total: 2,
  });
  m.experiment.mockResolvedValue(DETAIL);
  m.metricsSchema.mockResolvedValue({ metrics: {} });
  mLineage.mockResolvedValue({ root: { verstr: "a" }, upstream: [], downstream: [] });
});

const wrap = (ui: ReactNode) => renderWithClient(<MemoryRouter>{ui}</MemoryRouter>);
const props = (id: string) => JSON.parse(screen.getByTestId(id).getAttribute("data-props")!);
const base = { v: 1, id: "p", app: "my_app" };
const query = { query: "metrics.loss < 1" };
const one = { verstrs: ["a"] };

describe("Panel", () => {
  it("curves: overlays the query's runs", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "curves", runs: query, keys: ["loss"], smoothing: 0.5, log_y: true }} />);
    await waitFor(() => expect(props("OverlayChart").verstrs).toEqual(["a", "b"]));
    expect(props("OverlayChart")).toMatchObject({ app: "my_app", keys: ["loss"], smoothing: 0.5, logY: true });
    expect(m.experimentsPaged).toHaveBeenCalledWith("w", "my_app", expect.objectContaining({ query: "metrics.loss < 1" }));
  });

  it("curves: pinned runs need no fetch", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "curves", runs: { verstrs: ["x", "y"] }, keys: ["loss"] }} />);
    expect(props("OverlayChart").verstrs).toEqual(["x", "y"]);
    expect(m.experimentsPaged).not.toHaveBeenCalled();
  });

  it.each([
    ["bar", { metric: "loss" }, "MetricBarChart", { metricCols: ["loss"] }],
    ["scatter", { x: "params.lr", y: "loss" }, "MetricScatter", { initialX: "lr", initialY: "loss", paramCols: ["lr"] }],
    ["parallel", { columns: ["params.lr", "loss"] }, "ParallelCoordinates", { metricCols: ["loss"], paramCols: ["lr"] }],
    ["importance", { metric: "loss" }, "ParamImportance", { defaultMetric: "loss" }],
    ["grouped", { group_by: "params.lr", metric: "loss" }, "GroupedMetrics", { metricCols: ["loss"], initialGroup: "lr" }],
  ])("%s: renders query rows", async (type, extra, comp, expected) => {
    wrap(<Panel ws="w" spec={{ ...base, type, runs: query, ...extra }} />);
    await waitFor(() => expect(props(comp).rows).toHaveLength(2));
    expect(props(comp)).toMatchObject(expected);
    expect(m.experimentsColumns).toHaveBeenCalledWith(
      "w", "my_app", expect.arrayContaining(["metrics.loss"]), expect.objectContaining({ query: "metrics.loss < 1" }),
    );
  });

  it("bar: pinned runs come from their details", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "bar", runs: { verstrs: ["a", "b"] }, metric: "loss" }} />);
    await waitFor(() => expect(props("MetricBarChart").rows).toHaveLength(2));
    expect(m.experiment).toHaveBeenCalledWith("w", "my_app", "b");
    expect(m.experimentsColumns).not.toHaveBeenCalled();
  });

  it("leaderboard: a read-only table", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "leaderboard", runs: query, columns: ["loss"], params: ["lr"] }} />);
    expect(await screen.findByText("0.3")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("media: one key", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "media", runs: one, key: "img" }} />);
    await waitFor(() => expect(props("MediaImages").media).toEqual({ img: DETAIL.media.img }));
  });

  it("media: a fixed step keeps only that step", async () => {
    m.experiment.mockResolvedValue({ ...DETAIL, media: { img: [{ step: 1, path: "a" }, { step: 2, path: "b" }] } });
    wrap(<Panel ws="w" spec={{ ...base, type: "media", runs: one, key: "img", step: 2 }} />);
    await waitFor(() => expect(props("MediaImages").media).toEqual({ img: [{ step: 2, path: "b" }] }));
  });

  it("table: the item at the path", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "table", runs: one, path: "tables/preds/1.json" }} />);
    await waitFor(() => expect(props("MediaTable").tables).toEqual({ preds: DETAIL.tables.preds }));
    expect(props("MediaTable").verstr).toBe("a");
  });

  it("histogram: one key", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "histogram", runs: one, key: "grads" }} />);
    await waitFor(() => expect(props("RunHistograms").totals).toEqual({ grads: 3 }));
  });

  it("lineage: fetches at the spec's depth", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "lineage", runs: one, depth: 2 }} />);
    await screen.findByTestId("LineageView");
    expect(mLineage).toHaveBeenCalledWith("w", "my_app", "a", 2);
  });

  it("run: a compact card with status, metrics, params and a link", async () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "run", runs: one }} />);
    expect(await screen.findByText("acc")).toBeInTheDocument();
    expect(screen.getByText(/succeeded/i)).toBeInTheDocument();
    expect(screen.getByText("lr")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/ws/w/app/my_app/run/a");
  });

  it("invalid spec: an error box", () => {
    wrap(<Panel ws="w" spec={{ ...base, type: "nope", runs: one }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("unknown panel type nope");
  });
});

type Cb = (entries: { isIntersecting: boolean }[]) => void;
const observers: Cb[] = [];
class FakeIO {
  constructor(cb: Cb) { observers.push(cb); }
  observe() {}
  disconnect() {}
}

describe("Panel in a report", () => {
  const original = globalThis.IntersectionObserver;
  afterEach(() => { globalThis.IntersectionObserver = original; observers.length = 0; });

  const block = (id: string, extra: string) =>
    "```vmn-panel\nv: 1\nid: " + id + "\napp: my_app\n" + extra + "```\n\n";

  it("an invalid panel does not stop the rest of the report", async () => {
    const src = "# Report\n\n" + block("bad", "type: bar\nruns: {query: x}\n") +
      block("ok", "type: run\nruns: {verstrs: [a]}\n") + "tail text\n";
    wrap(<Markdown ws="w" source={src} />);
    expect(screen.getByRole("alert")).toHaveTextContent("metric");
    expect(screen.getByText("tail text")).toBeInTheDocument();
    expect(await screen.findByText("acc")).toBeInTheDocument();
  });

  it("only visible panels fetch", async () => {
    globalThis.IntersectionObserver = FakeIO as unknown as typeof IntersectionObserver;
    const src = block("p1", "type: run\nruns: {verstrs: [a]}\n") + block("p2", "type: run\nruns: {verstrs: [b]}\n");
    wrap(<Markdown ws="w" source={src} />);
    expect(observers).toHaveLength(2);
    expect(m.experiment).not.toHaveBeenCalled();
    act(() => observers[0]([{ isIntersecting: true }]));
    await waitFor(() => expect(m.experiment).toHaveBeenCalledWith("w", "my_app", "a"));
    expect(m.experiment).not.toHaveBeenCalledWith("w", "my_app", "b");
  });
});
