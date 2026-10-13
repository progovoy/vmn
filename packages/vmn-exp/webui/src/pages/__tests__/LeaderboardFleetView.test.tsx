import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

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
  m.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
});

describe("Leaderboard as an outer-run management view", () => {
  it("asks the server for the newest run number first by default", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    m.experimentsPaged.mockResolvedValue({ rows: [row(1)], total: 1 });
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const calls = [...m.experiments.mock.calls, ...m.experimentsPaged.mock.calls];
    expect(JSON.stringify(calls[calls.length - 1])).toContain('"idx"');
  });

  it("lays rows out in normal table flow, not absolutely positioned", async () => {
    m.experiments.mockResolvedValue(page([row(1), row(2)]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    document.querySelectorAll("tbody tr.row").forEach((tr) => {
      expect((tr as HTMLElement).style.position).not.toBe("absolute");
    });
  });

  it("pins the status column together with the experiment column", async () => {
    m.experiments.mockResolvedValue(page([row(1)]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    const status = document.querySelector("tbody td.status-cell") as HTMLElement;
    expect(status.style.position).toBe("sticky");
  });
});
