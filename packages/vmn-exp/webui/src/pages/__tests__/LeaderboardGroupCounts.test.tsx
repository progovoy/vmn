/** Plan 22 F10: while grouped, the board shows each group's counts in five
 *  columns (total / waiting / running / done / failed), filled on the group
 *  header rows only; their headers sort the groups by that count. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
  aggregates: {}, rows: INNER, rows_total: 4, rows_unfiltered: 4,
});
const grouped = (groups: RunGroup[]) => ({ groups, total_groups: groups.length, total_rows: 4, running: 1, aggregate: "mean" });
const header = () => document.querySelector("tbody tr.group-row") as HTMLElement;
const cell = (tr: Element, id: string) => tr.querySelector(`td[data-col-id="${id}"]`) as HTMLElement;
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

describe("the group count columns (plan 22 F10)", () => {
  it("show total / waiting / running / done / failed under one header group", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(headIds().filter((id) => COUNTS.includes(id!))).toEqual(COUNTS);
    const group = document.querySelector("thead th.lb-group") as HTMLTableCellElement;
    expect(group).toHaveAttribute("colspan", "5");
    expect(group.querySelector(".lb-group-label")?.textContent).toBe("Runs in group");
  });

  it("fill the group header row from its counts, stuck counted as failed; run rows stay blank", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(COUNTS.map((id) => cell(header(), id).textContent)).toEqual(["4", "0", "1", "1", "2"]);
    expect(cell(header(), "c:failed")).toHaveClass("tone-failed");
    expect(cell(header(), "c:waiting")).toHaveClass("count-zero");
    for (const tr of document.querySelectorAll("tbody tr.row")) {
      for (const id of COUNTS) expect(cell(tr, id).textContent).toBe("");
    }
  });

  it("leave the header's own count line to the size while they show", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    expect(header().querySelector(".group-counts")?.textContent).toBe("4 runs");
    // A screen reader still hears the counts in words.
    expect(header().querySelector(".sr-only")?.textContent).toBe("Group sweep: 4 runs, 1 running, 1 stuck, 1 failed");
  });

  it("give the count line its full wording back once every count column is hidden", async () => {
    renderBoard(`/ws/test/app/my-app?${COUNTS.map((id) => `hide=${id}`).join("&")}`);
    await waitFor(() => expect(header()).toBeTruthy());
    expect(headIds().filter((id) => COUNTS.includes(id!))).toEqual([]);
    expect(document.querySelector("thead th.lb-group")).toBeNull();
    expect(header().querySelector(".group-counts")?.textContent).toBe("4 runs · 1 running · 1 stuck · 1 failed");
  });

  it("hide one at a time with hide=", async () => {
    renderBoard("/ws/test/app/my-app?hide=c:waiting");
    await waitFor(() => expect(header()).toBeTruthy());
    expect(headIds().filter((id) => COUNTS.includes(id!))).toEqual(["c:total", "c:running", "c:done", "c:failed"]);
  });

  it("sort the groups by their count: sort=c:<name> goes to the grouped list, most first, then flips", async () => {
    renderBoard();
    await waitFor(() => expect(header()).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /sort groups by failed/i }));
    await waitFor(() => expect(m.experimentGroups.mock.calls.slice(-1)[0][2]).toMatchObject({ sort: "c:failed", order: "desc" }));
    expect(urlParams().get("sort")).toBe("c:failed");
    expect(document.querySelector('thead th[data-col-id="c:failed"]')).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(screen.getByRole("button", { name: /sort groups by failed/i }));
    await waitFor(() => expect(m.experimentGroups.mock.calls.slice(-1)[0][2]).toMatchObject({ sort: "c:failed", order: "asc" }));
  });

  it("never print a count sort as a CLI flag", async () => {
    renderBoard("/ws/test/app/my-app?sort=c:total&order=desc");
    await waitFor(() => expect(header()).toBeTruthy());
    expect(document.querySelector(".cli-card")?.textContent).not.toContain("c:total");
  });
});

describe("the flat board (group=none)", () => {
  it("has no count columns, none to pick, and drops a count sort left in the URL", async () => {
    renderBoard("/ws/test/app/my-app?group=none&sort=c:total&order=desc");
    await screen.findByRole("link", { name: v(3) });
    expect(headIds().filter((id) => COUNTS.includes(id!))).toEqual([]);
    expect(m.experimentGroups).not.toHaveBeenCalled();
    expect(m.experimentsPaged).not.toHaveBeenCalled();
    expect(m.experiments.mock.calls[0][2]).toBe("idx");
  });
});
