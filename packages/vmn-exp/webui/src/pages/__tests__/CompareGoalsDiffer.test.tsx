import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: {
    experimentsDiff: vi.fn(),
    recentExperiments: vi.fn(),
    experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import Compare from "../Compare/ComparePage";
import { MetricDelta } from "../../components/RunChangesParts";
import type { DiffDelta } from "../../types";

/** Plan 32 F9: two runs declaring different goals for a metric give its
 *  delta no direction; the delta says the goals differ instead of a verdict. */
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const CONFLICT: DiffDelta = {
  from: 0.5, to: 0.3, goal: null, param: false, goal_conflict: true, goals: ["min", "max"],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.recentExperiments.mockResolvedValue([]);
});

describe("a delta whose runs declare different goals", () => {
  it("says goals differ on the Compare code tab, in a neutral tone", async () => {
    m.experimentsDiff.mockResolvedValue({
      from_verstr: "a", to_verstr: "b", metrics_delta: { loss: CONFLICT }, diff: "",
    });
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/ws/w/app/app/compare-runs?tab=code&sel=a&sel=b"]}>
          <Routes>
            <Route path="/ws/:ws/app/:app/compare-runs" element={<Compare />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("loss");

    expect(screen.getByText("goals differ")).toHaveAttribute("title", "the runs declare min vs max");
    expect(screen.getByText("-0.2").style.color).toBe("var(--text-3)");
  });

  it("says goals differ on the run page's Changes card", () => {
    render(<MetricDelta deltas={{ loss: CONFLICT }} />);

    expect(screen.getByText("goals differ")).toHaveAttribute("title", "the runs declare min vs max");
  });
});
