import { describe, it, expect, vi, beforeEach } from "vitest";
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
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  const rows = [row(1, { metrics: { loss: 0.3 } })];
  m.experiments.mockResolvedValue(page(rows));
  m.experimentsPaged.mockResolvedValue({ rows, total: rows.length });
});

/** jsdom lays nothing out: give the scroller a size and a scroll position. */
function scrollTo(el: HTMLElement, left: number, content = 2000, view = 1000) {
  Object.defineProperty(el, "scrollWidth", { configurable: true, value: content });
  Object.defineProperty(el, "clientWidth", { configurable: true, value: view });
  el.scrollLeft = left;
  fireEvent.scroll(el);
}

describe("the leaderboard's overflow cue", () => {
  it("fades the right edge while more columns are to the right, and drops it at the end", async () => {
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const scroller = document.querySelector(".tbl-scroll") as HTMLElement;
    const card = scroller.closest(".lb-card") as HTMLElement;
    expect(card.querySelector(".lb-edge-fade")).toHaveAttribute("aria-hidden", "true");

    scrollTo(scroller, 0);
    await waitFor(() => expect(card).toHaveClass("more-right"));
    scrollTo(scroller, 1000);
    await waitFor(() => expect(card).not.toHaveClass("more-right"));
  });

  it("shows no cue when every column fits", async () => {
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const scroller = document.querySelector(".tbl-scroll") as HTMLElement;
    scrollTo(scroller, 0, 900, 1000);
    await waitFor(() => expect(scroller.closest(".lb-card")).not.toHaveClass("more-right"));
  });
});
