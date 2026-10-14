/** The selection follows the user across an app's views: a job picked on
 *  the Jobs view (one run, the outer itself) is still picked on All runs,
 *  and runs of several jobs add up in one tray. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../../api", () => ({
  api: {
    experiments: vi.fn(), experimentsPaged: vi.fn(), experimentsColumns: vi.fn(),
    experimentGroups: vi.fn(), experimentGroupRows: vi.fn(),
    metricsSchema: vi.fn(), facets: vi.fn(), config: vi.fn(), experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getTotalSize: () => count * estimateSize(),
    scrollToIndex: () => {},
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * estimateSize(), size: estimateSize(), end: (index + 1) * estimateSize(),
      })),
  }),
}));

import { api } from "../../../api";
import { readPicks, writePicks } from "../../../util/runSelection";
import { jobsPage, notFound, renderExperiments, singleRow, topRow } from "./jobsHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const GRID = topRow(2, { name: "grid" });
const INNER = singleRow(3, { name: "inner", depth: 1, kind: "inner", root: "0.0.9-dev.x", parent: "0.0.9-dev.x" });
const board = (rows: object[]) => Object.assign([...rows], { total: rows.length });
const tray = () => screen.findByRole("region", { name: "Selection" });
const switcher = () => screen.getByRole("group", { name: "Experiments view" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(notFound());
  m.experimentsColumns.mockRejectedValue(notFound());
  m.config.mockRejectedValue(notFound());
  m.experimentsPaged.mockResolvedValue(jobsPage([GRID, singleRow(1, { name: "solo" })]));
  m.experiments.mockResolvedValue(board([INNER, singleRow(1, { name: "solo" })]));
});

describe("the app-wide selection", () => {
  it("counts a picked job on the Jobs view as one run, the job itself", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${GRID.verstr}` }));
    const sel = await tray();
    expect(within(sel).getByText("1", { selector: ".sel-badge" })).toBeInTheDocument();
    expect(within(sel).getByRole("status")).toHaveTextContent("1 selected from 1 outer run");
    expect(readPicks("test", "my-app")).toEqual([{ verstr: GRID.verstr, job: GRID.verstr, name: "grid", idx: 2 }]);
  });

  it("keeps the Jobs view's picks on All runs, adding runs of other jobs", async () => {
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${GRID.verstr}` }));
    fireEvent.click(within(switcher()).getByRole("button", { name: "All runs" }));
    await screen.findByRole("link", { name: "inner" });
    expect(within(await tray()).getByText("1", { selector: ".sel-badge" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${INNER.verstr}` }));
    await waitFor(async () =>
      expect(within(await tray()).getByRole("status")).toHaveTextContent("2 selected from 2 outer runs"));
  });

  it("shows picks made on another page when the page opens", async () => {
    writePicks("test", "my-app", [{ verstr: "elsewhere", job: "J" }]);
    renderExperiments();
    await screen.findByRole("link", { name: "grid" });
    expect(within(await tray()).getByRole("status")).toHaveTextContent("1 selected from 1 outer run");
  });
});
