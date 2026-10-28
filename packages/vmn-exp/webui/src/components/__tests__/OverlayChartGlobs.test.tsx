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

describe("OverlayChart keys as globs (curves panels)", () => {
  it("draws one chart per key a glob matches", async () => {
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["e*", "l?ss"]} />);
    await waitFor(() => expect(instances).toHaveLength(2));
    expect(screen.getByText("epoch")).toBeInTheDocument();
    expect(screen.getByText("loss")).toBeInTheDocument();
    expect(screen.queryByText("acc")).toBeNull();
  });

  it("joins the matched keys on the x metric", async () => {
    renderWithClient(<OverlayChart ws="w" app="my-app" verstrs={RUNS} keys={["[al]*"]} x="epoch" />);
    await waitFor(() => expect(mockedBatch).toHaveBeenCalledWith(
      "w", "my-app", RUNS, ["acc", "loss"], 1000, { acc: "epoch", loss: "epoch" },
    ));
  });
});
