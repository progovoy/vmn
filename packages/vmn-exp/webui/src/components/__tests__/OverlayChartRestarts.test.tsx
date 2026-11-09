/** Compare's and an outer run's overlaid curves note a metric whose steps
 *  went back in some runs, as the run page's chart does, from the `/series`
 *  answer's `step_restarts`. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";

vi.mock("uplot", async () => await import("./fakeUPlot"));
vi.mock("../../apiSeries", () => ({
  fetchSeriesBatch: vi.fn(),
  fetchRunStatuses: vi.fn(),
}));

import { fetchRunStatuses, fetchSeriesBatch } from "../../apiSeries";
import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import OverlayChart from "../OverlayChart";

const mockedBatch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;
const mockedStatuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;

const RUNS = ["a", "b", "c"];
const curve = () => [0, 1, 2].map((i) => ({ step: i, value: 1 - i * 0.1, ts: null }));
const batch = (step_restarts: Record<string, Record<string, { from: number; to: number }>>) => ({
  series: Object.fromEntries(RUNS.map((v) => [v, { loss: curve(), acc: curve() }])),
  series_total: {}, step_metrics: {}, missing: [], step_restarts,
});

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  mockedStatuses.mockResolvedValue({});
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("overlaid curves of a metric whose steps went back", () => {
  it("names the one run and where its steps went back", async () => {
    mockedBatch.mockResolvedValue(batch({ a: { loss: { from: 9, to: 3 } } }));
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["loss", "acc"]} />);
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    expect(screen.getByTestId("overlay-restart-loss").textContent)
      .toBe("steps went back in a: from 9 to 3");
    expect(screen.queryByTestId("overlay-restart-acc")).toBeNull();
  });

  it("counts several runs, each named in its title", async () => {
    mockedBatch.mockResolvedValue(batch({
      a: { loss: { from: 9, to: 3 } }, c: { loss: { from: 5, to: 0 } },
    }));
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["loss"]} />);
    const note = await screen.findByTestId("overlay-restart-loss");
    expect(note.textContent).toBe("steps went back in 2 runs");
    expect(note).toHaveAttribute("title", "a: steps went back from 9 to 3\nc: steps went back from 5 to 0");
  });
});
