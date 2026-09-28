import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: {
    experimentsDiff: vi.fn(), metricsSchema: vi.fn(),
    recentExperiments: vi.fn(), experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import Compare from "../Compare";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderCompare(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/ws/w/app/app/compare?v=a&to=b"]}>
        <Routes><Route path="/ws/:ws/app/:app/compare" element={<Compare />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentsDiff.mockResolvedValue({ from_verstr: "a", to_verstr: "b", metrics_delta: {}, diff: "" });
  m.metricsSchema.mockResolvedValue({});
  m.recentExperiments.mockResolvedValue([]);
});

describe("Compare cache", () => {
  it("paints a revisited diff at once", async () => {
    const client = createQueryClient();
    const first = renderCompare(client);
    await screen.findByText("Code diff");
    first.unmount();
    renderCompare(client);
    expect(screen.getByText("Code diff")).toBeInTheDocument();
  });
});
