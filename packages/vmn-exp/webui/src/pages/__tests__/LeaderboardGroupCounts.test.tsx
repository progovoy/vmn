/** Plan 22 F13: a group's run counts belong to its head (the outer run), so
 *  they sit in its header row's own cell — a bar and the counts in words —
 *  not in table columns; the Group by menu sorts the groups by a count. */
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
import type { RunGroup } from "../../apiGroups";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const COUNTS = ["c:total", "c:waiting", "c:running", "c:done", "c:failed"];
const facets = { branches: ["main"], metric_keys: ["loss"], param_keys: [], tag_keys: [], param_values: {}, parented: 2, total: 3 };
const INNER = [row(2, { kind: "inner", parent: v(1), depth: 1 }), row(3, { kind: "inner", parent: v(1), depth: 1, status: "failed" })];

const sweep = (): RunGroup => ({
  key: v(1), label: v(1),
  target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "failed", metrics: {} },
  counts: { total: 4, running: 1, waiting: 0, done: 1, failed: 1, stuck: 1 },
  aggregates: {}, rows: INNER, rows_total: 4, rows_unfiltered: 4, clause: null, loose: false,
});
const grouped = (groups: RunGroup[]) => ({ groups, total_groups: groups.length, total_rows: 4, running: 1, aggregate: "mean" });
const header = () => document.querySelector("tbody tr.group-row") as HTMLElement;
const headIds = () => [...document.querySelectorAll("thead th[data-col-id]")].map((th) => (th as HTMLElement).dataset.colId);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
  m.experiments.mockResolvedValue(page([row(1), ...INNER]));
  m.experimentsPaged.mockResolvedValue(page([row(1), ...INNER]));
  m.facets.mockResolvedValue(facets);
  m.experimentGroups.mockResolvedValue(grouped([sweep()]));
});

const segments = (tr: Element) => [...tr.querySelectorAll(".group-bar .group-bar-seg")]
  .map((el) => [(el as HTMLElement).dataset.tone, (el as HTMLElement).style.width]);
const sortMenu = () => {
  fireEvent.click(screen.getByRole("button", { name: /^group by/i }));
  return screen.getByRole("group", { name: "Sort groups" });
};
const lastGroupsCall = () => m.experimentGroups.mock.calls.slice(-1)[0][2];

describe("a group's run counts (plan 22 F13)", () => {
  it("are no table columns: no count column and no header group, even with show=", async () => {
    renderBoard(`/ws/test/app/my-app?${COUNTS.map((id) => `show=${id}`).join("&")}`);
    await waitFor(() => expect(header()).toBeTruthy());
    expect(headIds().filter((id) => COUNTS.includes(id!))).toEqual([]);
    expect(document.querySelector("thead .lb-group-row")).toBeNull();
    for (const tr of document.querySelectorAll("tbody tr")) {
      for (const id of COUNTS) expect(tr.querySelector(`td[data-col-id="${id}"]`)).toBeNull();
    }
  });

  it("read in words on the head run's row", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(header().querySelector(".group-counts")?.textContent).toBe("4 runs · 1 running · 1 stuck · 1 failed");
    expect(header().querySelector(".sr-only")?.textContent).toBe("Group sweep: 4 runs, 1 running, 1 stuck, 1 failed");
  });

  it("fill a bar on the head run's row, finished runs first, hidden from a screen reader", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(segments(header())).toEqual([["done", "25%"], ["failed", "25%"], ["stuck", "25%"], ["running", "25%"]]);
    expect(header().querySelector(".group-bar")).toHaveAttribute("aria-hidden", "true");
    for (const tr of document.querySelectorAll("tbody tr.row")) expect(tr.querySelector(".group-bar")).toBeNull();
  });

  it("leave the bar out of a group of one run", async () => {
    m.experimentGroups.mockResolvedValue(grouped([{
      ...sweep(), counts: { total: 1, running: 0, waiting: 0, done: 1, failed: 0, stuck: 0 },
      rows: INNER.slice(0, 1), rows_total: 1, rows_unfiltered: 1,
    }]));
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(header().querySelector(".group-counts")?.textContent).toBe("1 run · all succeeded");
    expect(header().querySelector(".group-bar")).toBeNull();
  });

  it("sort the groups from the Group by menu: sort=c:<name>, most first", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    fireEvent.click(within(sortMenu()).getByRole("menuitemradio", { name: "failed" }));
    await waitFor(() => expect(lastGroupsCall()).toMatchObject({ sort: "c:failed", order: "desc" }));
    expect(urlParams().get("sort")).toBe("c:failed");
    expect(document.querySelector(".board-caption-sort")?.textContent).toBe("groups sorted by failed runs, most first");
    // The menu stays open after the pick, the count checked.
    const sort = screen.getByRole("group", { name: "Sort groups" });
    expect(within(sort).getByRole("menuitemradio", { name: "failed" })).toHaveAttribute("aria-checked", "true");
  });

  it("go back to the aggregate's order from the menu", async () => {
    renderBoard("/ws/test/app/my-app?sort=c:total&order=desc");
    await waitFor(() => expect(header()).toBeTruthy());
    fireEvent.click(within(sortMenu()).getByRole("menuitemradio", { name: "aggregate" }));
    await waitFor(() => expect(urlParams().get("sort")).toBeNull());
    expect(urlParams().get("order")).toBeNull();
  });

  it("never print a count sort as a CLI flag", async () => {
    renderBoard("/ws/test/app/my-app?sort=c:total&order=desc");
    await waitFor(() => expect(header()).toBeTruthy());
    expect(document.querySelector(".cli-card")?.textContent).not.toContain("c:total");
  });
});

describe("the flat board (group=none)", () => {
  it("drops a count sort left in the URL", async () => {
    renderBoard("/ws/test/app/my-app?group=none&sort=c:total&order=desc");
    await screen.findByRole("link", { name: v(3) });
    expect(m.experimentGroups).not.toHaveBeenCalled();
    expect(m.experimentsPaged).not.toHaveBeenCalled();
    expect(m.experiments.mock.calls[0][2]).toBe("idx");
  });
});
