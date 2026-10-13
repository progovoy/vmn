/** The Charts tab on a grouped board (plan 22 G7): every charted run in its
 *  group's colour, with a legend naming the groups. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";

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
import { runColor } from "../../util";
import { NO_GROUP_COLOR } from "../../util/chartGroups";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const counts = { total: 2, running: 0, waiting: 0, done: 2, failed: 0, stuck: 0 };
const OUTER = row(1, { kind: "outer", name: "sweep", children: [v(2), v(3)], metrics: { loss: 0.9 } });
const INNER = [2, 3].map((i) => row(i, { kind: "inner", parent: v(1), depth: 1, metrics: { loss: i / 10 } }));
const LONE = row(4, { metrics: { loss: 0.5 } });
const sweep = (): RunGroup => ({
  key: v(1), label: v(1),
  target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: null, metrics: {} },
  counts, aggregates: {}, rows: INNER, rows_total: 2,
});
const noParent = (): RunGroup => ({
  key: NONE_GROUP, label: "(no parent run)", target: null, counts, aggregates: {}, rows: [OUTER, LONE], rows_total: 2,
});
const facets = (parented: number) => ({
  branches: ["main"], metric_keys: ["loss"], param_keys: [], tag_keys: [], param_values: {}, parented, total: 6,
});
// Every filtered run, one in a group the board has not loaded yet.
const columns = {
  verstrs: [v(1), v(2), v(3), v(4), v(9)], idx: [1, 2, 3, 4, 9],
  columns: {
    "metrics.loss": [0.9, 0.2, 0.3, 0.5, 0.1],
    "group:parent": [NONE_GROUP, v(1), v(1), NONE_GROUP, v(7)],
  },
  total: 6,
};

const legend = () => within(screen.getByRole("list", { name: "Colour by group" }))
  .getAllByRole("listitem").map((li) => li.textContent);
const barColor = (verstr: string) =>
  (screen.getByTitle(new RegExp(`^${verstr.replaceAll(".", "\\.")}:`)).querySelector('[data-testid="bar-fill"]') as HTMLElement)
    .style.background;

/** The bar chart loads lazily: the first one can take a while. */
const bars = () => screen.findAllByTestId("bar-fill", {}, { timeout: 4000 });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.facets.mockResolvedValue(facets(2));
  m.experimentGroups.mockResolvedValue({ groups: [sweep(), noParent()], total_groups: 3, total_rows: 6 });
  m.experiments.mockResolvedValue(page([OUTER, ...INNER, LONE], 6));
  m.experimentsPaged.mockResolvedValue({ rows: [OUTER, ...INNER, LONE], total: 6 });
  m.experimentsColumns.mockResolvedValue(columns);
});

describe("the Charts tab on a grouped board", () => {
  it("asks for each run's group and colours every charted run by it, the board's groups first", async () => {
    renderBoard("/ws/test/app/my-app?view=bar");
    await waitFor(() => expect(legend()).toEqual(["sweep2", `${v(7)}1`, "(no parent run)2"]));
    expect(m.experimentsColumns).toHaveBeenCalledWith(
      "test", "my-app", ["metrics.loss", "group:parent"], expect.objectContaining({ sort: "idx" }),
    );
    await bars();
    expect(barColor(v(2))).toBe(runColor(0));
    expect(barColor(v(9))).toBe(runColor(1));
    expect(barColor(v(4))).toBe(NO_GROUP_COLOR);
  });

  it("colours only the selected runs by group while rows are selected (F7)", async () => {
    renderBoard(`/ws/test/app/my-app?view=bar&sel=${v(3)}&sel=${v(4)}`);
    await waitFor(() => expect(legend()).toEqual(["sweep1", "(no parent run)1"]));
    expect(await bars()).toHaveLength(2);
    expect(barColor(v(3))).toBe(runColor(0));
    expect(barColor(v(4))).toBe(NO_GROUP_COLOR);
  });

  it("colours the loaded rows by their loaded groups on a server without the columns endpoint", async () => {
    m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
    renderBoard("/ws/test/app/my-app?view=bar");
    await waitFor(() => expect(legend()).toEqual(["sweep2", "(no parent run)2"]));
    await bars();
    expect(barColor(v(3))).toBe(runColor(0));
    expect(barColor(v(1))).toBe(NO_GROUP_COLOR);
  });

  it("keeps the usual colours, and asks for no group, on an ungrouped board", async () => {
    m.facets.mockResolvedValue(facets(0));
    renderBoard("/ws/test/app/my-app?view=bar");
    await waitFor(() => expect(m.experimentsColumns).toHaveBeenCalled());
    await bars();
    expect(m.experimentsColumns.mock.calls[0][2]).toEqual(["metrics.loss"]);
    expect(screen.queryByRole("list", { name: "Colour by group" })).toBeNull();
  });
});
