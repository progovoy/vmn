import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const heads = () => [...document.querySelectorAll("thead th")] as HTMLElement[];
const headers = () => heads().map((th) => th.dataset.colId);
const head = (id: string) => document.querySelector(`thead th[data-col-id="${id}"]`) as HTMLElement;
const px = (el: HTMLElement) => Number.parseFloat(el.style.width);

async function board() {
  m.experiments.mockResolvedValue(page([
    row(1, { metrics: { loss: 0.3, acc: 0.9 }, started_at: "2026-01-01T00:00:00Z", finished_at: null }),
  ]));
  const utils = renderBoard();
  await screen.findByText("0.0.1-dev.x");
  return utils;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("leaderboard date columns", () => {
  it("are wide enough for a date and time by default", async () => {
    await board();
    expect(px(head("c:started"))).toBeGreaterThanOrEqual(140);
    expect(px(head("c:ended"))).toBeGreaterThanOrEqual(140);
  });

  it("sort by the run's start, newest first, then flip on a second click", async () => {
    await board();
    fireEvent.click(head("c:started"));
    await waitFor(() => expect(urlParams().get("sort")).toBe("started_at"));
    expect(urlParams().get("order")).toBe("desc");
    fireEvent.click(head("c:started"));
    await waitFor(() => expect(urlParams().get("order")).toBe("asc"));
  });

  it("sort by the run's end", async () => {
    await board();
    fireEvent.click(head("c:ended"));
    await waitFor(() => expect(urlParams().get("sort")).toBe("finished_at"));
    await waitFor(() => {
      const calls = [...m.experiments.mock.calls, ...m.experimentsPaged.mock.calls];
      expect(JSON.stringify(calls[calls.length - 1])).toContain('"finished_at"');
    });
  });
});

describe("leaderboard column resizing", () => {
  it("widens a column by dragging its header edge, and keeps it across reloads", async () => {
    const { unmount } = await board();
    const before = px(head("m:loss"));
    const grip = head("m:loss").querySelector(".col-resize") as HTMLElement;
    fireEvent.mouseDown(grip, { clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 560 });
    fireEvent.mouseUp(window, { clientX: 560 });
    await waitFor(() => expect(px(head("m:loss"))).toBe(before + 60));
    const col = document.querySelectorAll("colgroup col")[headers().indexOf("m:loss")] as HTMLElement;
    expect(px(col)).toBe(before + 60);

    unmount();
    await board();
    expect(px(head("m:loss"))).toBe(before + 60);
  });

  it("never shrinks a column below a usable minimum", async () => {
    await board();
    const grip = head("c:started").querySelector(".col-resize") as HTMLElement;
    fireEvent.mouseDown(grip, { clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 0 });
    fireEvent.mouseUp(window, { clientX: 0 });
    await waitFor(() => expect(px(head("c:started"))).toBeGreaterThanOrEqual(40));
  });

  it("does not sort when the resize grip is clicked", async () => {
    await board();
    const grip = head("c:started").querySelector(".col-resize") as HTMLElement;
    fireEvent.mouseDown(grip, { clientX: 500 });
    fireEvent.mouseUp(window, { clientX: 500 });
    fireEvent.click(grip);
    expect(urlParams().get("sort")).toBeNull();
  });

  it("offers a grip on every column, pinned ones included", async () => {
    await board();
    heads().forEach((th) => expect(th.querySelector(".col-resize")).not.toBeNull());
  });
});

describe("leaderboard column reordering", () => {
  const drag = (from: string, to: string) => {
    fireEvent.dragStart(head(from));
    fireEvent.dragOver(head(to));
    fireEvent.drop(head(to));
    fireEvent.dragEnd(head(from));
  };

  it("moves a column in front of the header it is dropped on, header and cells alike", async () => {
    await board();
    drag("m:loss", "c:total");
    await waitFor(() => expect(headers().indexOf("m:loss")).toBe(headers().indexOf("c:total") - 1));
    const cells = [...document.querySelectorAll("tbody tr.row td")].map((td) => (td as HTMLElement).dataset.colId);
    expect(cells).toEqual(headers());
  });

  it("keeps the new order across reloads", async () => {
    const { unmount } = await board();
    drag("c:ended", "c:total");
    await waitFor(() => expect(headers().indexOf("c:ended")).toBe(headers().indexOf("c:total") - 1));
    unmount();
    await board();
    expect(headers().indexOf("c:ended")).toBe(headers().indexOf("c:total") - 1);
  });

  it("leaves the pinned columns (check, #, status, experiment) where they are", async () => {
    await board();
    const pinned = ["check", "idx", "status", "experiment"];
    pinned.forEach((id) => expect(head(id).draggable).toBe(false));
    drag("m:loss", "status");
    expect(headers().slice(0, 4)).toEqual(pinned);
  });

  it("resets widths and order from the toolbar", async () => {
    await board();
    const defaults = headers();
    drag("m:loss", "c:total");
    await waitFor(() => expect(headers()).not.toEqual(defaults));
    fireEvent.click(screen.getByRole("button", { name: /reset columns/i }));
    await waitFor(() => expect(headers()).toEqual(defaults));
  });
});

describe("leaderboard width", () => {
  const RealObserver = globalThis.ResizeObserver;
  beforeEach(() => {
    globalThis.ResizeObserver = class {
      constructor(private cb: ResizeObserverCallback) {}
      observe() { this.cb([{ contentRect: { width: 1800 } } as ResizeObserverEntry], this as never); }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });
  afterEach(() => { globalThis.ResizeObserver = RealObserver; });

  const tableWidth = () => heads().reduce((sum, th) => sum + px(th), 0);

  it("fills the space it is given by widening the experiment column", async () => {
    await board();
    await waitFor(() => expect(tableWidth()).toBe(1800));
    expect(px(document.querySelector("table.lb-table") as HTMLElement)).toBe(1800);
  });

  it("keeps a width the user set on the experiment column", async () => {
    localStorage.setItem("vmn_columns:test/my-app", JSON.stringify({ widths: { experiment: 320 }, order: [] }));
    await board();
    expect(px(head("experiment"))).toBe(320);
  });
});
