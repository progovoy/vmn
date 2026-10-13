/** Plan 20 C7: the board's chrome, distilled. The page head names the app
 *  once with its run count and carries New run / Views / Columns; the live
 *  status, the sort and the "best in column" legend are the table's caption;
 *  at most 7 controls stand between the h1 and the table. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";

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
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const KNOWN_APP = {
  total: 3, counts: { created: 0, running: 0, stuck: 0, succeeded: 3, failed: 0 }, failed_recent: 0, rollup: null,
};
const ROWS = [1, 2, 3].map((i) => row(i, { metrics: { loss: i / 10 }, params: { lr: i } }));

const FOCUSABLE = "a[href], button, input, select, textarea, [tabindex]";
/** The controls Tab stops at between *from* and *to*, in document order. */
function tabStopsBetween(from: Element, to: Element): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) =>
    !(el as HTMLButtonElement).disabled && el.tabIndex >= 0
    && from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING
    && el.compareDocumentPosition(to) & Node.DOCUMENT_POSITION_FOLLOWING
    && !to.contains(el));
}

async function board(path?: string) {
  renderBoard(path);
  await screen.findByRole("link", { name: ROWS[0].verstr });
  await screen.findByRole("button", { name: "New run" });
  return {
    h1: screen.getByRole("heading", { level: 1 }),
    grid: screen.getByRole("grid", { name: "experiments" }),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(ROWS));
  m.experimentsPaged.mockResolvedValue({ rows: ROWS, total: 3 });
  m.apps.mockResolvedValue([{ name: "my/app", experiments: 3, versions: 1 }]);
  appStatus.mockResolvedValue(KNOWN_APP);
});

describe("the distilled board toolbar (C7)", () => {
  it("has at most 7 controls between the h1 and the table in the default view", async () => {
    const { h1, grid } = await board();
    const stops = tabStopsBetween(h1, grid);
    expect(stops.length, stops.map((s) => s.textContent || s.getAttribute("aria-label")).join(" | "))
      .toBeLessThanOrEqual(7);
  });

  it("names the app once in the page head, with its run count", async () => {
    const { h1 } = await board();
    expect(h1).toHaveTextContent(/^my\/app$/);
    const head = h1.closest(".page-head") as HTMLElement;
    expect(head).toHaveTextContent("3 runs");
    expect(screen.queryByText("experiment leaderboard")).toBeNull();
    // The app's name shows nowhere else above the table.
    const above = [...document.body.querySelectorAll("*")].filter(
      (el) => el.children.length === 0 && el.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_PRECEDING
        && /my\/app/.test(el.textContent ?? "") && !el.closest("[role=grid]") && !el.closest(".cli-card"),
    );
    expect(above).toEqual([]);
  });

  it("puts New run (primary), Views and Columns in the page head", async () => {
    const { h1 } = await board();
    const head = h1.closest(".page-head") as HTMLElement;
    expect(within(head).getByRole("button", { name: "New run" })).toHaveClass("primary");
    expect(within(head).getByRole("button", { name: /Views/ })).toBeInTheDocument();
    expect(within(head).getByRole("button", { name: /Columns/ })).toBeInTheDocument();
  });

  it("captions the table with the legend, the sort and the live status", async () => {
    const { grid } = await board("/ws/test/app/my-app?sort=loss");
    const caption = document.getElementById(grid.getAttribute("aria-describedby") ?? "") as HTMLElement;
    expect(caption).not.toBeNull();
    expect(caption).toHaveTextContent("best in column");
    expect(caption).toHaveTextContent(/sorted by loss/);
    expect(within(caption).getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    // Nothing of it sits between the h1 and the table.
    expect(caption.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("keeps Pause in the caption while a run is live", async () => {
    m.experiments.mockResolvedValue(page([row(1, { status: "running" }), ...ROWS.slice(1)]));
    const { h1, grid } = await board();
    const pause = screen.getByRole("button", { name: "Pause" });
    expect(tabStopsBetween(h1, grid)).not.toContain(pause);
  });
});
