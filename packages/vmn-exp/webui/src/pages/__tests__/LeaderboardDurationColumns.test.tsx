/** Plan 28 N4 + FS: queue time, duration and the duration ratio against
 *  siblings are picker columns (`show=c:queue|c:duration|c:ratio`) that sort
 *  the board server-side. */
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const head = (id: string) => document.querySelector(`thead th[data-col-id="${id}"]`) as HTMLElement;
const cell = (id: string) => document.querySelector(`tbody td[data-col-id="${id}"]`) as HTMLElement;

async function board(path = "/ws/test/app/my-app?show=c:queue&show=c:duration&show=c:ratio") {
  m.experiments.mockResolvedValue(page([
    row(1, { queue_sec: 125, duration_sec: 7300, duration_ratio: 3.14159, params: { lr: 0.1, opt: "adam" } }),
    row(2, { queue_sec: null, duration_sec: null, duration_ratio: null, params: { lr: 0.2, opt: "sgd" } }),
  ]));
  renderBoard(path);
  await screen.findByText("0.0.1-dev.x");
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("leaderboard duration columns", () => {
  it("show queue time, duration and the ratio to the siblings' median", async () => {
    await board();
    expect(cell("c:queue").textContent).toBe("2m");
    expect(cell("c:duration").textContent).toBe("2h");
    expect(cell("c:ratio").textContent).toBe("3.1× siblings");
    const blank = document.querySelectorAll('tbody td[data-col-id="c:ratio"]')[1];
    expect(blank.textContent).toBe("—");
  });

  it.each([["c:queue", "queue_sec"], ["c:duration", "duration_sec"], ["c:ratio", "duration_ratio"]])(
    "%s sorts by %s, highest first, then flips",
    async (id, sort) => {
      await board();
      fireEvent.click(head(id));
      await waitFor(() => expect(urlParams().get("sort")).toBe(sort));
      expect(urlParams().get("order")).toBe("desc");
      fireEvent.click(head(id));
      await waitFor(() => expect(urlParams().get("order")).toBe("asc"));
    },
  );
});
