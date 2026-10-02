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

const RUNS = ["a", "b"];
const curve = () => [0, 1, 2].map((i) => ({ step: i, value: 1 - i * 0.1, ts: null }));
const batch = () => ({
  series: Object.fromEntries(RUNS.map((v) => [v, { loss: curve(), acc: curve(), epoch: curve() }])),
  series_total: {}, step_metrics: {}, missing: [],
});

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  mockedStatuses.mockResolvedValue({});
  mockedBatch.mockResolvedValue(batch());
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("OverlayChart from props alone", () => {
  it("fetches the runs and draws one chart per key, one series per run", async () => {
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["loss"]} maxPoints={500} />);
    await waitFor(() => expect(instances).toHaveLength(1));
    expect(mockedBatch).toHaveBeenCalledWith("w", "my-app", RUNS, null, 500);
    expect((instances[0].opts.series as unknown[]).length).toBe(3);
    expect(screen.getByText("loss")).toBeInTheDocument();
  });

  it("joins its keys on the x metric prop", async () => {
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["acc", "loss"]} x="epoch" />);
    await waitFor(() => expect(mockedBatch).toHaveBeenCalledWith(
      "w", "my-app", RUNS, ["acc", "loss"], 1000, { acc: "epoch", loss: "epoch" },
    ));
  });

  it("hides the runs in the hidden prop", async () => {
    renderWithClient(
      <OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["loss"]} hidden={new Set(["b"])} />,
    );
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    await waitFor(() => expect(instances[0].setSeries).toHaveBeenCalledWith(2, { show: false }));
  });
});
