import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    experimentsImportance: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/MetricScatter", () => ({
  default: ({ initialX, initialY }: { initialX?: string; initialY?: string }) => (
    <div>scatter:{initialX}:{initialY}</div>
  ),
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
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([
    row(1, { metrics: { loss: 0.3, acc: 0.1 }, params: { lr: 1 } }),
    row(2, { metrics: { loss: 0.2, acc: 0.2 }, params: { lr: 2 } }),
  ]));
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 2 });
  m.experimentsImportance.mockResolvedValue([
    { param: "lr", importance: 1, correlation: -0.9, spearman: -1, kind: "numeric", n: 2 },
  ]);
});

describe("the leaderboard's importance panel", () => {
  it("ranks params for the sort metric under the board's filter", async () => {
    renderBoard("/ws/test/app/my-app?view=importance&sort=acc&status=failed");
    expect((await screen.findByTestId("importance-param")).textContent).toBe("lr");
    expect(m.experimentsImportance).toHaveBeenCalledWith(
      "test", "my-app", "acc", expect.objectContaining({ status: "failed" }),
    );
  });

  it("is reachable from the chart switcher and opens the scatter on a param", async () => {
    renderBoard("/ws/test/app/my-app");
    fireEvent.click(await screen.findByRole("button", { name: "Importance" }));
    await waitFor(() => expect(urlParams().get("view")).toBe("importance"));
    fireEvent.click(await screen.findByTestId("importance-param"));
    expect(await screen.findByText(/^scatter:lr:/)).toBeInTheDocument();
  });
});
