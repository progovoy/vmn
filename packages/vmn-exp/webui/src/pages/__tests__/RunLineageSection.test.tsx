import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn() }));

import { api } from "../../api";
import { runLineage } from "../../apiRun";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

describe("Run page lineage", () => {
  it("shows the run's upstream runs", async () => {
    mockedApi.experiment.mockResolvedValue({
      metadata: { verstr: "0.0.1-dev.eval", timestamp: "2026-01-01T12:00:00Z", note: "" },
      metrics: {}, series: {}, log: [], patches: {},
    });
    mockedApi.metricsSchema.mockResolvedValue({});
    (runLineage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      app: "my/app", verstr: "0.0.1-dev.eval", downstream: [], models: [], truncated: false,
      upstream: [{
        app: "my/app", verstr: "0.0.1-dev.train", name: "train", timestamp: null,
        status: "succeeded", depth: 1, found: true, links: [],
      }],
    });
    renderWithClient(
      <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.1-dev.eval"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "train" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.1-dev.train",
    );
    expect(runLineage).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.eval", 1);
  });
});
