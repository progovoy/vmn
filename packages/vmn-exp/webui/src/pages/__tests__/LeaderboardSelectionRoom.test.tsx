import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

import { api } from "../../api";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
/** The bar's bottom offset plus a gap above it (styles/board.css). */
const ROOM_PX = 24 + 12;

const setup = globalThis.ResizeObserver;
let barHeight = 60;

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([1, 2, 3].map((i) => row(i)), 3));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 3 });
  // A bar that measures *barHeight* tall, like one whose actions wrapped.
  globalThis.ResizeObserver = class {
    constructor(private cb: ResizeObserverCallback) {}
    observe(target: Element) {
      Object.defineProperty(target, "offsetHeight", { configurable: true, get: () => barHeight });
      const contentRect = { width: 1200, height: barHeight } as DOMRectReadOnly;
      this.cb([{ target, contentRect } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => { globalThis.ResizeObserver = setup; });

describe("the room under the selection bar", () => {
  it("follows the bar's height, so a bar wrapped onto two lines still hides nothing", async () => {
    barHeight = 124;
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    await screen.findByRole("region", { name: "Selection" });
    const spacer = document.querySelector(".sel-bar-spacer") as HTMLElement;
    await waitFor(() => expect(spacer.style.height).toBe(`${124 + ROOM_PX}px`));
  });
});

describe("the status header", () => {
  it("carries the status column's class, so it lines up with the pills", async () => {
    renderBoard();
    await screen.findByRole("link", { name: v(1) });
    expect(screen.getByRole("columnheader", { name: /status/i })).toHaveClass("status-col-head");
  });
});
