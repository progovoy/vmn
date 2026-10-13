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
const headers = () => [...document.querySelectorAll("thead th")].map((th) => th.textContent?.trim());

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

  it("sums an outer run's inner runs in one inner column", async () => {
    m.experiments.mockResolvedValue(page([
      row(1, {
        kind: "outer", depth: 0, children: ["a", "b", "c", "d", "e", "f"],
        child_counts: { created: 1, running: 2, succeeded: 2, failed: 1 },
        started_at: "2026-01-01T00:00:00Z", finished_at: null,
      }),
    ]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    // Plan 20 C2: one inner column instead of five counts; the dates are picker columns (D11).
    const h = headers();
    expect(h).toContain("inner");
    ["total", "waiting", "running", "done", "failed", "started", "ended"].forEach((c) => expect(h).not.toContain(c));
    const cell = document.querySelector('tbody td[data-col-id="c:inner"] [aria-hidden]')?.textContent;
    expect(cell).toBe("6 · 2 running · 1 failed · 1 waiting · 2 done");
  });

  it("lets the Columns picker hide an outer-run column", async () => {
    m.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.3 }, kind: "outer", children: ["a"] })]));
    renderBoard();
    await screen.findByText("0.0.1-dev.x");
    expect(headers()).toContain("inner");
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: "inner" }));
    await waitFor(() => expect(headers()).not.toContain("inner"));
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
