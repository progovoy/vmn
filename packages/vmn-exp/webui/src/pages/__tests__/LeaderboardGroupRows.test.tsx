/** The grouped board (plan 22 W2: G1, G4, G5): a flat list of every run,
 *  and with a grouping, group header rows from the grouped list payload. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(),
    experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    config: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { NONE_GROUP, type RunGroup } from "../../apiGroups";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const facets = (parented: number) => ({
  branches: ["main"], metric_keys: ["loss", "acc"], param_keys: [], tag_keys: [],
  param_values: {}, parented, total: 4,
});
const counts = (extra = {}) => ({ total: 3, running: 1, waiting: 0, done: 1, failed: 1, stuck: 0, ...extra });
const agg = (mean: number, extra = {}) => ({ mean, best: mean / 2, median: mean, min: mean / 2, max: mean * 2, n: 3, ...extra });

const OUTER = row(1, { kind: "outer", name: "sweep", children: [v(2), v(3)], tree_status: "failed", metrics: { loss: 0.9 } });
const INNER = [row(2, { kind: "inner", parent: v(1), depth: 1, metrics: { loss: 0.2 } }),
  row(3, { kind: "inner", parent: v(1), depth: 1, status: "failed", metrics: { loss: 0.4 } })];
const LONE = row(4, { metrics: { loss: 0.5 } });

function sweepGroup(extra: Partial<RunGroup> = {}): RunGroup {
  return {
    key: v(1), label: v(1),
    target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "failed", metrics: { loss: 0.91 } },
    counts: counts(), aggregates: { loss: agg(0.3), acc: agg(0.8, { best: null }) }, rows: INNER, rows_total: 2,
    rows_unfiltered: (extra.counts ?? counts()).total, loose: false, clause: null, ...extra,
  };
}
// The runs with no parent that head no group (plan 22 F12): the sweep's run is its header.
const loose = (): RunGroup => ({
  key: NONE_GROUP, label: "(none)", target: null, loose: true, counts: counts({ total: 1, running: 0, failed: 0 }),
  aggregates: {}, rows: [LONE], rows_total: 1, rows_unfiltered: 1, clause: null,
});
// A group that is not loose, built on *base*'s fields.
const plain = (base: RunGroup, extra: Partial<RunGroup>): RunGroup => ({ ...base, loose: false, ...extra });
const grouped = (groups: RunGroup[]) => ({ groups, total_groups: groups.length, total_rows: 4 });
const headerRows = () => [...document.querySelectorAll("tbody tr.group-row")] as HTMLElement[];
const header = (text: string) => headerRows().find((r) => r.textContent?.includes(text)) as HTMLElement;
const runLinks = () => [...document.querySelectorAll("tbody tr.row .run-link")].map((a) => a.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
  m.experiments.mockResolvedValue(page([OUTER, ...INNER, LONE]));
  m.facets.mockResolvedValue(facets(2));
  m.experimentGroups.mockResolvedValue(grouped([sweepGroup(), loose()]));
});

describe("the flat board (group=none)", () => {
  it("lists every run, outer, inner and single alike, with no fold and no inner counts", async () => {
    m.facets.mockResolvedValue(facets(0));
    renderBoard();
    await screen.findByRole("link", { name: v(4) });
    expect(runLinks()).toEqual(["sweep", v(2), v(3), v(4)]);
    expect(screen.queryByRole("button", { name: /^(expand|collapse) /i })).toBeNull();
    expect(document.querySelector(".exp-cell")?.textContent).not.toMatch(/inner/);
    const heads = [...document.querySelectorAll("thead th[data-col-id]")].map((th) => (th as HTMLElement).dataset.colId);
    expect(heads.filter((id) => /^c:(total|waiting|running|done|failed)$/.test(id ?? ""))).toEqual([]);
    expect(m.experimentGroups).not.toHaveBeenCalled();
  });
});

describe("the grouped board", () => {
  it("asks for the groups once the facets say runs have a parent, leaving agg to the server", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(m.experiments).not.toHaveBeenCalled();
    expect(m.experimentGroups).toHaveBeenCalledTimes(1);
    const opts = m.experimentGroups.mock.calls[0][2];
    expect(opts).toMatchObject({ group: "parent", sort: "idx", offset: 0 });
    expect(opts.agg).toBeUndefined();
  });

  it("heads a link group with its target run: a link, its tree status and the counts in words", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    const h = header("sweep");
    expect(within(h).getByRole("link", { name: "sweep" })).toHaveAttribute("href", `/ws/test/app/my-app/run/${v(1)}`);
    expect(h.querySelector('td[data-col-id="idx"]')?.textContent).toBe("@1");
    expect(h.querySelector(".status-pill")?.className).toContain("failed");
    expect(h.querySelector(".group-counts")?.textContent).toBe("3 runs · 1 running · 1 failed");
    expect(h.querySelector(".group-counts .tone-failed")?.textContent).toBe("1 failed");
    expect(within(h).getByText("Group sweep: 3 runs, 1 running, 1 failed")).toHaveClass("sr-only");
  });

  it("says `2 of 5` when the filters leave part of the group (plan 22 F1)", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ counts: counts({ total: 2 }), rows_unfiltered: 5 }), loose()]));
    renderBoard("/ws/test/app/my-app?status=failed");
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    const h = header("sweep");
    expect(h.querySelector(".group-counts")?.textContent).toBe("2 of 5 runs · 1 running · 1 failed");
    expect(within(h).getByText("Group sweep: 2 of 5 runs, 1 running, 1 failed")).toHaveClass("sr-only");
  });

  it("shows the group's aggregate per metric, the target's own value, and names the aggregate", async () => {
    renderBoard("/ws/test/app/my-app?show=m:acc");
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    const loss = header("sweep").querySelector('td[data-col-id="m:loss"]') as HTMLElement;
    expect(loss.querySelector(".group-agg")?.textContent).toBe("0.3");
    expect(loss).toHaveAttribute("title", "mean of 3");
    expect(loss.querySelector(".group-own")?.textContent).toBe("own 0.91");
    expect(document.querySelector('thead th[data-col-id="m:loss"] .agg-tag')?.textContent).toBe("mean");
  });

  it("sends a chosen agg= and shows that aggregate, the mean for a metric without a goal", async () => {
    renderBoard("/ws/test/app/my-app?agg=best&show=m:acc");
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(m.experimentGroups.mock.calls[0][2]).toMatchObject({ agg: "best" });
    const cell = (id: string) => header("sweep").querySelector(`td[data-col-id="${id}"]`) as HTMLElement;
    expect(cell("m:loss").querySelector(".group-agg")?.textContent).toBe("0.15");
    expect(cell("m:loss")).toHaveAttribute("title", "best of 3");
    expect(cell("m:acc").querySelector(".group-agg")?.textContent).toBe("0.8");
    expect(cell("m:acc")).toHaveAttribute("title", "mean of 3 (no goal)");
  });

  it("puts each group's rows under its header, and the loose rows after the groups, with no header (plan 22 F12)", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    const order = [...document.querySelectorAll("tbody tr")].map((tr) =>
      tr.classList.contains("group-row") ? `[${tr.querySelector(".group-label")?.textContent}]` : tr.querySelector(".run-link")?.textContent);
    expect(order).toEqual(["[sweep]", v(2), v(3), v(4)]);
    expect(screen.queryByText("(none)")).toBeNull();
    expect(screen.getAllByRole("button", { name: /^(Collapse|Expand) group/ })).toHaveLength(1);
  });

  it("folds a group shut and open again, remembering it in collapse=", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    const fold = within(header("sweep")).getByRole("button", { name: "Collapse group sweep" });
    expect(fold).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(fold);
    await waitFor(() => expect(screen.queryByRole("link", { name: v(2) })).toBeNull());
    expect(urlParams().getAll("collapse")).toEqual([v(1)]);
    fireEvent.click(within(header("sweep")).getByRole("button", { name: "Expand group sweep" }));
    expect(await screen.findByRole("link", { name: v(2) })).toBeInTheDocument();
    expect(urlParams().getAll("collapse")).toEqual([]);
  });

  it("opens with the groups collapse= names shut", async () => {
    renderBoard(`/ws/test/app/my-app?collapse=${v(1)}`);
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(screen.queryByRole("link", { name: v(2) })).toBeNull();
    expect(screen.getByRole("link", { name: v(4) })).toBeInTheDocument();
  });

  it("loads the rest of a group from its +N more row", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ rows: [INNER[0]], rows_total: 2 })]));
    m.experimentGroupRows.mockResolvedValue({ ...sweepGroup(), rows: [INNER[1]] });
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "+1 more" }));
    expect(await screen.findByRole("link", { name: v(3) })).toBeInTheDocument();
    expect(m.experimentGroupRows.mock.calls[0][2]).toBe(v(1));
    expect(m.experimentGroupRows.mock.calls[0][3]).toMatchObject({ group: "parent", offset: 1, limit: 1 });
    expect(screen.queryByRole("button", { name: /more$/ })).toBeNull();
  });

  it("keeps each group's own depth across a refresh: the opened one whole, a sibling at its first 10", async () => {
    const runs = (p: number, n: number) => Array.from({ length: n }, (_, i) =>
      row(p + i + 1, { kind: "inner", parent: v(p), depth: 1 }));
    const all: Record<string, ReturnType<typeof row>[]> = { [v(100)]: runs(100, 12), [v(200)]: runs(200, 15) };
    const group = (key: string, rows: ReturnType<typeof row>[]): RunGroup =>
      sweepGroup({ key, label: key, target: null, rows, rows_total: all[key].length });
    m.experimentGroups.mockImplementation(async (_ws: string, _app: string, o: { rowsPerGroup?: number }) => ({
      groups: Object.keys(all).map((k) => group(k, all[k].slice(0, o.rowsPerGroup ?? 10))),
      total_groups: 2, total_rows: 27,
    }));
    m.experimentGroupRows.mockImplementation(async (_ws: string, _app: string, key: string, o: { offset: number; limit: number }) =>
      group(key, all[key].slice(o.offset, o.offset + o.limit)));
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "+2 more" }));
    expect(await screen.findByRole("link", { name: v(112) })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(m.experimentGroups).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(runLinks()).toHaveLength(22));
    expect(screen.getByRole("link", { name: v(112) })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+2 more" })).toBeNull();
    expect(screen.getByRole("button", { name: "+5 more" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: v(211) })).toBeNull();
  });

  it("pages groups: Load more asks for the groups after the loaded ones", async () => {
    const third = plain(loose(), { key: "x", label: "x", rows: [row(9)], rows_total: 1 });
    m.experimentGroups
      .mockResolvedValueOnce({ ...grouped([sweepGroup(), third]), total_groups: 3 })
      .mockResolvedValueOnce({ ...grouped([loose()]), total_groups: 3 });
    renderBoard();
    fireEvent.click(await screen.findByRole("button", { name: "Load more (1 group remaining)" }));
    await waitFor(() => expect(screen.getByRole("link", { name: v(4) })).toBeInTheDocument());
    expect(headerRows()).toHaveLength(2);
    expect(m.experimentGroups.mock.calls[1][2]).toMatchObject({ group: "parent", offset: 2 });
    expect(screen.getByRole("link", { name: v(9) })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^load more/i })).toBeNull();
  });

  it("orders groups by the sorted column: the server's group order, the sort sent with it", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup({ key: v(7), label: v(7), target: null }), sweepGroup()]));
    fireEvent.click(screen.getByRole("button", { name: /sort by loss/i }));
    await waitFor(() => expect(headerRows()[0].textContent).toContain(v(7)));
    expect(m.experimentGroups.mock.calls.slice(-1)[0][2]).toMatchObject({ sort: "loss", order: "asc" });
  });

  it("labels a code-state group by its verstr and a field group as field = value", async () => {
    const code = plain(loose(), { key: "0.1.0-dev.e71c74d.ba02c10", label: "0.1.0-dev.e71c74d.ba02c10" });
    m.experimentGroups.mockResolvedValue(grouped([code]));
    const { unmount } = renderBoard("/ws/test/app/my-app?group=code_verstr");
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(headerRows()[0].querySelector(".group-label")?.textContent).toBe("0.1.0-dev.e71c74d.ba02c10");
    expect(within(headerRows()[0]).queryByRole("link", { name: /0\.1\.0-dev\.e71c74d/ })).toBeNull();
    expect(headerRows()[0].textContent).toContain("0.0.1 · main");
    unmount();

    m.experimentGroups.mockResolvedValue(grouped([plain(loose(), { key: "main", label: "branch = main" })]));
    renderBoard("/ws/test/app/my-app?group=branch");
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(headerRows()[0].querySelector(".group-label")?.textContent).toBe("branch = main");
  });

  it("counts the runs of the grouped payload in the subtitle", async () => {
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(document.querySelector(".page-sub")?.textContent).toBe("2 runs · 4 incl. inner");
  });

  it("counts the whole board's runs while groups hold only their first rows", async () => {
    m.facets.mockResolvedValue({ ...facets(40), total: 50 });
    m.experimentGroups.mockResolvedValue({ ...grouped([sweepGroup({ rows_total: 40 }), loose()]), total_rows: 50 });
    renderBoard();
    await waitFor(() => expect(headerRows()).toHaveLength(1));
    expect(document.querySelector(".page-sub")?.textContent).toBe("10 runs · 50 incl. inner");
  });
});
