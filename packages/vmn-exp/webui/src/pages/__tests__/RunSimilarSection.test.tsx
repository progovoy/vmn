import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn() }));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));

import { api } from "../../api";
import { runLineage } from "../../apiRun";
import { runSimilar } from "../../apiSimilar";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

describe("Run page similar runs", () => {
  it("shows the runs most like this one", async () => {
    mockedApi.experiment.mockResolvedValue({
      metadata: { verstr: "0.0.1-dev.eval", timestamp: "2026-01-01T12:00:00Z", note: "" },
      metrics: {}, series: {}, log: [], patches: {},
    });
    mockedApi.metricsSchema.mockResolvedValue({});
    (runLineage as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      app: "my/app", verstr: "0.0.1-dev.eval", upstream: [], downstream: [], models: [], truncated: false,
    });
    (runSimilar as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      truncated: false,
      items: [{
        workspace: "test", app: "my/app", verstr: "0.0.1-dev.twin", name: "twin", score: 0.9,
        reasons: ["same dataset imagenet@3"], signals: {}, group_size: 1, goal: null,
        author: "bob@x.io", timestamp: null, status: "succeeded", note: null, intent: null,
      }],
    });
    renderWithClient(
      <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.1-dev.eval"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "twin" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.1-dev.twin",
    );
    expect(screen.getByText("same dataset imagenet@3")).toBeInTheDocument();
    expect(runSimilar).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.eval", { allApps: false });
  });
});
