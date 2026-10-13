/** Selection on the grouped board (plan 22 G7): a group header's checkbox
 *  selects the group's loaded rows, and Compare / Archive count rows, never
 *  the header's target run. */
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
    action: vi.fn(),
    job: vi.fn(),
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
import { location, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const counts = { total: 3, running: 0, waiting: 0, done: 3, failed: 0, stuck: 0 };
const INNER = [2, 3].map((i) => row(i, { kind: "inner", parent: v(1), depth: 1 }));
const LONE = row(4);

const sweep = (): RunGroup => ({
  key: v(1), label: v(1),
  target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "succeeded", metrics: {} },
  loose: false, counts, aggregates: {}, rows: INNER, rows_total: 3, rows_unfiltered: 3,
});
// The runs with no parent that head no group (plan 22 F12): the sweep's run is its header.
const loose = (): RunGroup => ({
  key: NONE_GROUP, label: "(none)", target: null, loose: true, counts: { ...counts, total: 1 },
  aggregates: {}, rows: [LONE], rows_total: 1, rows_unfiltered: 1,
});
const job = (status: string) => ({ id: "j1", status, command: [], exit_code: status === "running" ? null : 0, log: "" });

const header = (text: string) =>
  [...document.querySelectorAll("tbody tr.group-row")].find((r) => r.textContent?.includes(text)) as HTMLElement;
const groupBox = (name: string) =>
  within(header(name)).getByRole("checkbox", { name: `Select group ${name}` }) as HTMLInputElement;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.facets.mockResolvedValue({
    branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, parented: 2, total: 4,
  });
  m.experimentGroups.mockResolvedValue({ groups: [sweep(), loose()], total_groups: 2, total_rows: 4 });
  m.action.mockResolvedValue(job("running"));
  m.job.mockResolvedValue(job("succeeded"));
});

describe("a group header's checkbox", () => {
  it("selects the group's loaded rows, not its target run, and clears them again", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    fireEvent.click(groupBox("sweep"));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(2), v(3)]));
    expect(groupBox("sweep").checked).toBe(true);
    expect(groupBox("sweep").indeterminate).toBe(false);
    fireEvent.click(groupBox("sweep"));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
    expect(groupBox("sweep").checked).toBe(false);
  });

  it("shows indeterminate while only some of its rows are selected, and completes them on a click", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(2)}&sel=${v(4)}`);
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    expect(groupBox("sweep").indeterminate).toBe(true);
    expect(groupBox("sweep").checked).toBe(false);
    fireEvent.click(groupBox("sweep"));
    await waitFor(() => expect(urlParams().getAll("sel").sort()).toEqual([v(2), v(3), v(4)]));
    expect(groupBox("sweep").indeterminate).toBe(false);
  });

  it("selects a closed group's loaded rows too", async () => {
    renderBoard(`/ws/test/app/my-app?collapse=${encodeURIComponent(v(1))}`);
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    expect(screen.queryByRole("link", { name: v(2) })).toBeNull();
    fireEvent.click(groupBox("sweep"));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(2), v(3)]));
  });

  it("is not there for the loose runs, which have no header: each is selected on its own row", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    expect(screen.getAllByRole("checkbox", { name: /^Select group/ })).toEqual([groupBox("sweep")]);
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${v(4)}` }));
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([v(4)]));
    expect(groupBox("sweep").checked).toBe(false);
  });
});

describe("the selection bar on a grouped board", () => {
  it("counts the selected rows in Compare (N) and compares exactly them", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    fireEvent.click(groupBox("sweep"));
    const compare = await screen.findByRole("button", { name: "Compare (2)" });
    fireEvent.click(compare);
    await waitFor(() => expect(location.pathname).toBe("/ws/test/app/my-app/compare-runs"));
    expect(new URLSearchParams(location.search).getAll("sel")).toEqual([v(2), v(3)]);
  });

  it("archives the selected rows, not the header's target", async () => {
    renderBoard();
    await waitFor(() => expect(header("sweep")).toBeTruthy());
    fireEvent.click(groupBox("sweep"));
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Archive 2 runs?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_archive", { verstrs: [v(2), v(3)] });
  });
});
