/** The board's keys (plan 23 W8): j/k move from anywhere on the page, x
 *  selects, shift+x selects a range, o opens, / focuses the filter, Escape
 *  drops the row focus and the range anchor, ? lists them. */
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
import { location, page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const rowOf = (i: number) => screen.getByRole("link", { name: v(i) }).closest("tr")!;
const press = (key: string, extra: KeyboardEventInit = {}) => fireEvent.keyDown(document.activeElement ?? document.body, { key, ...extra });
const selected = () => urlParams().getAll("sel");

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.config.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiment.mockResolvedValue({ metadata: { verstr: "x" }, metrics: {}, series: {}, patches: {} });
  m.experiments.mockResolvedValue(page([row(1), row(2), row(3), row(4)]));
});

async function board(path?: string) {
  renderBoard(path);
  await screen.findByRole("link", { name: v(1) });
}

describe("board keys", () => {
  it("j and k move the active row from anywhere on the page", async () => {
    await board();
    fireEvent.keyDown(document.body, { key: "j" });
    expect(rowOf(1)).toHaveFocus();
    press("j");
    expect(rowOf(2)).toHaveFocus();
    press("k");
    expect(rowOf(1)).toHaveFocus();
  });

  it("x toggles the active row's selection", async () => {
    await board();
    press("j");
    press("x");
    await waitFor(() => expect(selected()).toEqual([v(1)]));
    press("x");
    await waitFor(() => expect(selected()).toEqual([]));
  });

  it("shift+x selects the range from the last toggled row", async () => {
    await board();
    press("j");
    press("x");
    await waitFor(() => expect(selected()).toEqual([v(1)]));
    press("j");
    press("j");
    press("X", { shiftKey: true });
    await waitFor(() => expect(new Set(selected())).toEqual(new Set([v(1), v(2), v(3)])));
  });

  it("Escape drops the row focus and the range anchor (the selection bar clears the selection)", async () => {
    await board();
    press("j");
    press("x");
    await waitFor(() => expect(selected()).toEqual([v(1)]));
    press("Escape");
    expect(rowOf(1)).not.toHaveFocus();
    await waitFor(() => expect(selected()).toEqual([]));
    press("j");
    press("j");
    press("X", { shiftKey: true });
    // No anchor left: a range from @1 would select @1 too.
    await waitFor(() => expect(selected()).toEqual([v(2)]));
  });

  it("o opens the active row", async () => {
    await board();
    press("j");
    press("j");
    press("o");
    await waitFor(() => expect(location.pathname).toBe(`/ws/test/app/my-app/run/${v(2)}`));
  });

  it("/ focuses the filter box", async () => {
    await board();
    press("j");
    press("/");
    expect(screen.getByRole("textbox", { name: "Filter query" })).toHaveFocus();
  });

  it("ignores keys typed into the filter, and keys with a modifier", async () => {
    await board();
    const box = screen.getByRole("textbox", { name: "Filter query" });
    box.focus();
    fireEvent.keyDown(box, { key: "j" });
    expect(box).toHaveFocus();
    fireEvent.keyDown(document.body, { key: "j", metaKey: true });
    fireEvent.keyDown(document.body, { key: "j", ctrlKey: true });
    expect(box).toHaveFocus();
    rowOf(1).focus();
    press("x", { altKey: true });
    expect(selected()).toEqual([]);
  });

  it("? opens a shortcut list, Escape closes it", async () => {
    await board();
    fireEvent.keyDown(document.body, { key: "?", shiftKey: true });
    const help = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(help).getByText("Select a range")).toBeInTheDocument();
    expect(within(help).getByText("Focus the filter")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("the toolbar's shortcuts button opens the same list", async () => {
    await board();
    const button = screen.getByRole("button", { name: "Keyboard shortcuts" });
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
});

describe("board keys, grouped", () => {
  const INNER = [row(2, { kind: "inner", parent: v(1), depth: 1 }), row(3, { kind: "inner", parent: v(1), depth: 1 })];
  beforeEach(() => {
    m.experiments.mockResolvedValue(page([row(1, { kind: "outer", name: "sweep", children: [v(2), v(3)] }), ...INNER]));
    m.facets.mockResolvedValue({
      branches: ["main"], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, parented: 2, total: 3,
    });
    m.experimentGroups.mockResolvedValue({
      groups: [{
        key: v(1), label: v(1),
        target: { verstr: v(1), idx: 1, name: "sweep", status: "succeeded", tree_status: "succeeded", metrics: {} },
        counts: { total: 5, running: 0, waiting: 0, done: 5, failed: 0, stuck: 0 },
        aggregates: {}, rows: INNER, rows_total: 5, rows_unfiltered: 5, loose: false,
      }],
      total_groups: 1, total_rows: 3,
    });
  });
  const rowAt = (i: number) => document.querySelector<HTMLElement>(`tbody tr[data-row-index="${i}"]`)!;

  it("x on a group header selects the group's loaded rows", async () => {
    renderBoard();
    await waitFor(() => expect(document.querySelector("tbody tr.group-row")).not.toBeNull());
    press("j");
    expect(rowAt(0)).toHaveFocus();
    press("x");
    await waitFor(() => expect(new Set(selected())).toEqual(new Set([v(2), v(3)])));
  });

  it("the +N more row keeps the table's tab stop once it is the active row", async () => {
    renderBoard();
    await waitFor(() => expect(document.querySelector("tbody tr.group-more")).not.toBeNull());
    const more = document.querySelector<HTMLElement>("tbody tr.group-more")!;
    for (let i = 0; i <= Number(more.dataset.rowIndex); i++) press("j");
    expect(more).toHaveFocus();
    expect(more).toHaveAttribute("tabindex", "0");
  });
});
