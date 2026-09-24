import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { screen, waitFor } from "@testing-library/react";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

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
vi.mock("../../components/MetricBarChart", () => ({
  default: ({ rows }: { rows: unknown[] }) => <div>bar:{rows.length}</div>,
}));
vi.mock("../../components/MetricScatter", () => ({
  default: ({ rows }: { rows: unknown[] }) => <div>scatter:{rows.length}</div>,
}));
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
const cols = {
  verstrs: ["a", "b", "c"], idx: [1, 2, 3],
  columns: { "metrics.loss": [0.3, 0.2, 0.1], "params.lr": [1, 2, 3] }, total: 3,
};

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.3 }, params: { lr: 1 } })], 3));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 3 });
});

describe("leaderboard charts cover the whole filtered set", () => {
  it("charts every matching run through experiments-columns", async () => {
    m.experimentsColumns.mockResolvedValue(cols);
    renderBoard("/ws/test/app/my-app?view=bar&status=failed");
    expect(await screen.findByText("bar:3")).toBeInTheDocument();
    expect(screen.getByText("charting 3 of 3 runs")).toBeInTheDocument();
    expect(m.experimentsColumns).toHaveBeenCalledWith(
      "test", "my-app", ["metrics.loss"], expect.objectContaining({ status: "failed" }),
    );
  });

  it("asks scatter for the params it plots too", async () => {
    m.experimentsColumns.mockResolvedValue(cols);
    renderBoard("/ws/test/app/my-app?view=scatter");
    expect(await screen.findByText("scatter:3")).toBeInTheDocument();
    expect(m.experimentsColumns).toHaveBeenCalledWith(
      "test", "my-app", ["metrics.loss", "params.lr"], expect.anything(),
    );
  });

  it("falls back to the loaded rows when the server has no columns endpoint", async () => {
    m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
    renderBoard("/ws/test/app/my-app?view=bar");
    await waitFor(() => expect(screen.getByText("charting the loaded 1 of 3")).toBeInTheDocument());
    expect(screen.getByText("bar:1")).toBeInTheDocument();
  });
});
