import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
import Compare from "../Compare";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderCompare() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/ws/w/app/app/compare?v=a&to=b"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/compare" element={<Compare />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.recentExperiments.mockResolvedValue([]);
});

describe("Compare delta coloring", () => {
  it("renders neutral color when goal is null", async () => {
    m.experimentsDiff.mockResolvedValue({
      from_verstr: "a",
      to_verstr: "b",
      metrics_delta: {
        some_metric: { from: 1.0, to: 2.0, goal: null, param: false },
      },
      diff: "",
    });
    renderCompare();
    await screen.findByText("some_metric");

    // The delta cell is +1: find it
    const deltaCell = screen.getByText("+1");
    // With goal=null the delta must be neutral (--text-3), not good/bad
    expect(deltaCell.style.color).toBe("var(--text-3)");
  });

  it("renders good color for goal=min negative delta", async () => {
    m.experimentsDiff.mockResolvedValue({
      from_verstr: "a",
      to_verstr: "b",
      metrics_delta: {
        loss: { from: 0.5, to: 0.3, goal: "min", param: false },
      },
      diff: "",
    });

    renderCompare();
    await screen.findByText("loss");

    const deltaCell = screen.getByText("-0.2");
    // Negative delta with goal=min is an improvement
    expect(deltaCell.style.color).toBe("var(--good)");
  });

  it("renders neutral color for param deltas", async () => {
    m.experimentsDiff.mockResolvedValue({
      from_verstr: "a",
      to_verstr: "b",
      metrics_delta: {
        lr: { from: 0.01, to: 0.001, goal: null, param: true },
      },
      diff: "",
    });

    renderCompare();
    await screen.findByText("lr");

    const deltaCell = screen.getByText("-0.009");
    expect(deltaCell.style.color).toBe("var(--text-3)");
  });
});
