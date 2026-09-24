import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: {
    experimentsDiff: vi.fn().mockResolvedValue({ from_verstr: "a", to_verstr: "b", metrics_delta: {}, diff: "" }),
    metricsSchema: vi.fn().mockResolvedValue({}),
    recentExperiments: vi.fn().mockResolvedValue([]),
    experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { createQueryClient } from "../../queryClient";
import Compare from "../Compare";

describe("Compare page", () => {
  it("links the pair to the N-run compare table", async () => {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/ws/w/app/app/compare?v=a&to=b"]}>
          <Routes><Route path="/ws/:ws/app/:app/compare" element={<Compare />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const link = await screen.findByRole("link", { name: /compare as table/i });
    expect(link).toHaveAttribute("href", "/ws/w/app/app/compare-runs?sel=a&sel=b");
  });
});
