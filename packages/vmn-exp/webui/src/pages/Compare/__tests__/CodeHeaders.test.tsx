/** M2 on the Code tab: the metric-delta headers name each side `@N name`,
 *  verstr in the title, uncapitalised (D3), with a copy button. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../../api", () => ({
  api: { experimentsDiff: vi.fn(), recentExperiments: vi.fn(), experimentsPaged: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../../api";
import { createQueryClient } from "../../../queryClient";
import ComparePage from "../ComparePage";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsDiff.mockResolvedValue({
    from_verstr: "0.0.1-dev.a", to_verstr: "0.0.2-dev.b",
    metrics_delta: { loss: { from: 1, to: 0.5, goal: "min", param: false } }, diff: "",
  });
  m.experimentsPaged.mockResolvedValue({
    rows: [
      { verstr: "0.0.1-dev.a", idx: 1, name: "baseline" },
      { verstr: "0.0.2-dev.b", idx: 2, name: null },
    ],
    total: 2,
  });
});

describe("Compare code tab delta headers", () => {
  it("read @N name with the verstr in the title, uncapitalised, with a copy button", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/ws/w/app/app/compare-runs?tab=code&sel=0.0.1-dev.a&sel=0.0.2-dev.b"]}>
          <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const head = await screen.findByRole("columnheader", { name: /@1 baseline/ });
    expect(head.className).toContain("compare-ident");
    expect(within(head).getByTitle("0.0.1-dev.a")).toHaveTextContent("@1 baseline");
    expect(within(head).getByRole("button", { name: "copy 0.0.1-dev.a" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /@2/ })).toHaveClass("compare-ident");
  });
});
