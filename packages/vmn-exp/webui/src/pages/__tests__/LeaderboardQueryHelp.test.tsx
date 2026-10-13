/** Plan 20 C5 on the board: the query help draws its fields and examples
 *  from this app's facets and loaded rows. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";

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
const ROWS = [
  row(1, { metrics: { val_loss: 0.5 }, params: { optimizer: "adam" }, tags: { team: "vision" } }),
  row(2, { metrics: { val_loss: 0.3 }, params: { optimizer: "sgd" } }),
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.metricsSchema.mockResolvedValue({ val_loss: { goal: "min" } });
  m.facets.mockResolvedValue({
    branches: ["feat/x", "main"], metric_keys: ["val_loss", "throughput"], param_keys: ["optimizer"], total: 2,
  });
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page(ROWS));
  m.experimentsPaged.mockResolvedValue({ rows: ROWS, total: 2 });
});

describe("the board's query help", () => {
  it("lists the app's keys and examples built from them", async () => {
    renderBoard();
    await screen.findByRole("link", { name: ROWS[0].verstr });
    await screen.findByText("feat/x");
    fireEvent.click(screen.getByRole("button", { name: "Query help" }));
    const dialog = screen.getByRole("dialog", { name: "Query help" });
    for (const k of ["metrics.val_loss", "metrics.throughput", "params.optimizer", "tags.team"]) {
      expect(within(dialog).getByText(k)).toBeInTheDocument();
    }
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "metrics.val_loss < 0.5", 'params.optimizer = "adam"', 'status = "failed" and branch = "feat/x"',
    ]);
  });
});
