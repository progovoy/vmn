/** A group's rows read as its members (plan 22 F11): indented under the
 *  header's label, a guide line from the fold down to the last member. */
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
import { NONE_GROUP, type RunGroup } from "../../apiGroups";
import { page, renderBoard, row } from "./leaderboardHarness";

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
// The runs with no parent that head no group (plan 22 F12).
const loose = (extra: Partial<RunGroup> = {}): RunGroup => ({
  key: NONE_GROUP, label: "(none)", target: null, loose: true, counts: counts({ total: 1, running: 0, failed: 0 }),
  aggregates: {}, rows: [LONE], rows_total: 1, rows_unfiltered: 1, clause: null, ...extra,
});
const grouped = (groups: RunGroup[]) => ({ groups, total_groups: groups.length, total_rows: 4 });
const headerRows = () => [...document.querySelectorAll("tbody tr.group-row")] as HTMLElement[];
const header = (text: string) => headerRows().find((r) => r.textContent?.includes(text)) as HTMLElement;


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

const member = (name: string) =>
  [...document.querySelectorAll("tbody tr.row")].find((r) => r.querySelector(".run-link")?.textContent === name) as HTMLElement;

describe("a group's members", () => {
  it("marks a group's rows as members, the last one as last", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    const [first, last] = INNER.map((r) => member(r.name ?? r.verstr));
    expect(first.classList.contains("group-member")).toBe(true);
    expect(first.classList.contains("group-last")).toBe(false);
    expect(last.classList.contains("group-member")).toBe(true);
    expect(last.classList.contains("group-last")).toBe(true);
    expect(first.querySelector("td.exp-cell .group-member-body .run-link")).toBeTruthy();
  });

  it("leaves the loose rows unmarked, after the groups, without a header of their own (plan 22 F12)", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    expect(headerRows()).toHaveLength(1);
    const lone = member(LONE.name ?? LONE.verstr);
    expect(lone.classList.contains("group-member")).toBe(false);
    expect(lone.querySelector(".group-member-body")).toBeNull();
    // The sweep's last member stays its last, though a loose row follows it.
    expect(member(v(3)).classList.contains("group-last")).toBe(true);
  });

  it("pages the loose rows from a plain +N more row, no one's member", async () => {
    m.experimentGroups.mockResolvedValue(grouped([sweepGroup(), loose({ rows_total: 3, rows_unfiltered: 3 })]));
    m.experimentGroupRows.mockResolvedValue(loose({ rows: [row(5), row(6)], rows_total: 3 }));
    renderBoard();
    const more = await screen.findByRole("button", { name: "+2 more" });
    expect(more.closest("tr")?.classList.contains("group-member")).toBe(false);
    fireEvent.click(more);
    expect(await screen.findByRole("link", { name: v(6) })).toBeInTheDocument();
    expect(m.experimentGroupRows.mock.calls[0][2]).toBe(NONE_GROUP);
    expect(m.experimentGroupRows.mock.calls[0][3]).toMatchObject({ group: "parent", offset: 1, limit: 2 });
    expect(member(v(6)).classList.contains("group-member")).toBe(false);
  });

  it("marks nothing with group=none", async () => {
    renderBoard("/ws/test/app/my-app?group=none");
    await waitFor(() => expect(document.querySelectorAll("tbody tr.row").length).toBe(4));
    expect(document.querySelectorAll("tr.group-member").length).toBe(0);
  });
});
