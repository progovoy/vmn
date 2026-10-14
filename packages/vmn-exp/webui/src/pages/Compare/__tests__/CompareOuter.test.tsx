/** Compare takes outer runs but guides: an outer's chip carries its badge,
 *  and one that logs no metrics itself gets a note offering its best run or
 *  its runs (at most 20) instead. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("uplot", async () => await import("../../../components/__tests__/fakeUPlot"));
vi.mock("../../../api", () => ({
  api: {
    experiment: vi.fn(), experimentsDiff: vi.fn(), metricsSchema: vi.fn(),
    recentExperiments: vi.fn(), experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));
vi.mock("../../../apiSeries", () => ({ fetchSeriesBatch: vi.fn(), fetchRunStatuses: vi.fn() }));
vi.mock("../../../apiJob", async (orig) => ({ ...(await orig<object>()), jobSummary: vi.fn() }));

import { api } from "../../../api";
import { jobSummary } from "../../../apiJob";
import { fetchRunStatuses, fetchSeriesBatch } from "../../../apiSeries";
import { enableCanvas, resetInstances } from "../../../components/__tests__/fakeUPlot";
import type { ExperimentDetail, ExperimentRow } from "../../../types";
import ComparePage from "../ComparePage";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const summary = jobSummary as unknown as ReturnType<typeof vi.fn>;
const kids = (n: number) => Array.from({ length: n }, (_, i) => `t${i + 1}`);

const OUTER = {
  verstr: "o", idx: 3, name: "kfold-cv", kind: "outer", children: kids(5), metrics: {}, params: { folds: 5 },
} as unknown as ExperimentRow;
const PLAIN = { verstr: "b", idx: 2, name: null, kind: "single", children: [], metrics: { loss: 0.2 } } as unknown as ExperimentRow;
let lookup: ExperimentRow[] = [OUTER, PLAIN];

const detail = (r: ExperimentRow): ExperimentDetail => ({
  metadata: { verstr: r.verstr }, idx: r.idx, name: r.name ?? null, params: r.params ?? {}, metrics: r.metrics,
  series: {}, patches: {},
  status: { kind: r.kind, children: r.children, fleet: { expected: 5, counts: { succeeded: r.children?.length ?? 0 } } },
} as unknown as ExperimentDetail);

const loc = { search: "" };
function Probe() {
  loc.search = useLocation().search;
  return null;
}
const sel = () => new URLSearchParams(loc.search).getAll("sel");

function renderPage(search: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs${search}`]}>
      <Probe />
      <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
    </MemoryRouter>,
  );
}

const scoped = (n: number) => ({ rows: kids(n).map((v, i) => ({ verstr: v, idx: 10 + i })), total: n });

beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  lookup = [OUTER, PLAIN];
  m.experiment.mockImplementation((_w: string, _a: string, v: string) => {
    const r = lookup.find((x) => x.verstr === v);
    return r ? Promise.resolve(detail(r)) : Promise.reject(Object.assign(new Error("nf"), { status: 404 }));
  });
  m.metricsSchema.mockResolvedValue({});
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsPaged.mockImplementation((_w: string, _a: string, opts: { scope?: string; limit?: number }) =>
    Promise.resolve(opts.scope ? scoped(Math.min(opts.limit ?? 5, 5)) : { rows: lookup, total: lookup.length }));
  (fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>).mockImplementation((_w: string, _a: string, vs: string[]) =>
    Promise.resolve({ series: Object.fromEntries(vs.map((v) => [v, {}])), missing: [] }));
  (fetchRunStatuses as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
  summary.mockResolvedValue({ top: [{ verstr: "t3", idx: 12, name: null, status: "succeeded", value: 0.1 }] });
});

const note = () => screen.findByRole("note");

describe("an outer run's chip", () => {
  it("carries the outer badge, linked to the outer run's page", async () => {
    renderPage("?sel=o&sel=b");
    const chips = await screen.findByRole("list", { name: "selected runs" });
    expect(await within(chips).findByRole("link", { name: "outer · 5 runs" }))
      .toHaveAttribute("href", "/ws/w/app/my-app/run/o");
    expect(within(chips).getAllByRole("link")).toHaveLength(1);
  });
});

describe("an outer run without metrics of its own", () => {
  it("gets a note on Curves", async () => {
    renderPage("?sel=o&sel=b");
    expect(await note()).toHaveTextContent("kfold-cv is an outer run of 5 runs and logs no metrics itself");
  });

  it("gets the note on Table too, but not on Code", async () => {
    const { unmount } = renderPage("?sel=o&sel=b&tab=table");
    expect(await note()).toHaveTextContent("kfold-cv is an outer run of 5 runs");
    unmount();
    m.experimentsDiff.mockResolvedValue({ from_verstr: "o", to_verstr: "b", metrics_delta: {}, diff: "" });
    renderPage("?sel=o&sel=b&tab=code");
    await screen.findByRole("list", { name: "selected runs" });
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalled());
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("swaps the outer for its best run", async () => {
    renderPage("?sel=o&sel=b");
    fireEvent.click(within(await note()).getByRole("button", { name: "Compare its best run" }));
    await waitFor(() => expect(sel()).toEqual(["t3", "b"]));
    expect(summary).toHaveBeenCalledWith("w", "my-app", "o");
  });

  it("without a goal, swaps in its first run", async () => {
    summary.mockResolvedValue({ top: [] });
    renderPage("?sel=o&sel=b");
    fireEvent.click(within(await note()).getByRole("button", { name: "Compare its best run" }));
    await waitFor(() => expect(sel()).toEqual(["t1", "b"]));
    expect(m.experimentsPaged).toHaveBeenCalledWith("w", "my-app",
      expect.objectContaining({ scope: "o", limit: 1, sort: "idx", order: "asc" }));
  });

  it("adds its runs", async () => {
    renderPage("?sel=o&sel=b");
    fireEvent.click(within(await note()).getByRole("button", { name: "Add its 5 runs" }));
    await waitFor(() => expect(sel()).toEqual(["o", "b", "t1", "t2", "t3", "t4", "t5"]));
  });

  it("adds at most 20, and says so", async () => {
    lookup = [{ ...OUTER, children: kids(30) }, PLAIN];
    renderPage("?sel=o&sel=b");
    const n = await note();
    expect(n).toHaveTextContent("kfold-cv is an outer run of 30 runs");
    fireEvent.click(within(n).getByRole("button", { name: "Add 20 of its 30 runs" }));
    expect(n).toHaveTextContent("capped at 20");
    await waitFor(() => expect(m.experimentsPaged).toHaveBeenCalledWith("w", "my-app",
      expect.objectContaining({ scope: "o", limit: 20 })));
  });
});

describe("an outer run that logs its own metrics", () => {
  it("compares normally, with no note", async () => {
    lookup = [{ ...OUTER, metrics: { acc_mean: 0.9 } } as ExperimentRow, PLAIN];
    renderPage("?sel=o&sel=b");
    const chips = await screen.findByRole("list", { name: "selected runs" });
    await within(chips).findByRole("link", { name: "outer · 5 runs" });
    expect(screen.queryByRole("note")).toBeNull();
  });
});
