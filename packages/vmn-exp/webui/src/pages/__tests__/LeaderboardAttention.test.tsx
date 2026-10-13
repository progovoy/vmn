/** Plan 20 C6 on the board: the attention strip sits above it, its links set
 *  the filter bar's token, and the rows behind a link are as many as it says
 *  (an inner run whose outer is filtered out still shows). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    apps: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
const appStatus = vi.hoisted(() => vi.fn());
vi.mock("../../apiShell", () => ({ apiShell: { appStatus: () => appStatus() } }));
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;

const OUTER = row(1, { kind: "outer", children: [v(2), v(3)], depth: 0, parent: null, status: "created", tree_status: "stuck" });
const INNER_OK = row(2, { kind: "inner", parent: v(1), depth: 1 });
const INNER_STUCK = row(3, { kind: "inner", parent: v(1), depth: 1, status: "stuck" });
const TOP_STUCK = row(4, { status: "stuck" });
const ALL = [TOP_STUCK, OUTER, INNER_OK, INNER_STUCK];
const STATUS = {
  total: 4, counts: { created: 1, running: 0, stuck: 2, succeeded: 1, failed: 0 }, failed_recent: 0, rollup: "stuck",
};
const tokens = () => within(screen.getByRole("list", { name: "Active filters" }))
  .queryAllByRole("listitem").map((li) => li.getAttribute("data-token"));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
  m.apps.mockResolvedValue([{ name: "my/app", experiments: 4, versions: 1 }]);
  m.experiments.mockImplementation((_ws: string, _app: string, _sort: string, status?: string) =>
    Promise.resolve(status === "stuck" ? page([TOP_STUCK, INNER_STUCK]) : page(ALL)));
  appStatus.mockResolvedValue(STATUS);
});

describe("the attention strip on the board", () => {
  it("shows above the filter bar what needs attention", async () => {
    renderBoard();
    const strip = (await screen.findByRole("link", { name: "2 stuck" })).closest('[role="status"]')!;
    expect(strip).not.toBeNull();
    const bar = screen.getByRole("list", { name: "Active filters" });
    expect(strip.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is absent while nothing needs attention", async () => {
    appStatus.mockResolvedValue({ ...STATUS, counts: { ...STATUS.counts, stuck: 0, running: 3 } });
    renderBoard();
    await screen.findByRole("link", { name: v(4) });
    expect(screen.queryByRole("link", { name: /stuck/ })).toBeNull();
  });

  it("its stuck link sets the status token and lists as many rows as it counts", async () => {
    renderBoard("/ws/test/app/my-app?q=metrics.loss%20%3C%201");
    fireEvent.click(await screen.findByRole("link", { name: "2 stuck" }));
    await waitFor(() => expect(urlParams().get("status")).toBe("stuck"));
    expect(urlParams().has("q")).toBe(false);
    await waitFor(() => expect(tokens()).toEqual(['status = "stuck"']));
    // The inner stuck run shows although its outer is not among the matches.
    expect(await screen.findByRole("link", { name: v(3) })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: v(4) })).toBeInTheDocument();
    const grid = screen.getByRole("grid", { name: "experiments" });
    const runLinks = within(grid).getAllByRole("link").filter((a) => /\/run\//.test(a.getAttribute("href") ?? ""));
    expect(runLinks).toHaveLength(STATUS.counts.stuck);
  });
});
