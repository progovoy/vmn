/** A run-vs-run diff the server could not build (a run without a base commit,
 *  a store workspace) comes back as `diff: null` with `diff_unavailable`: the
 *  Changes card and the Compare code tab say so instead of crashing. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));
vi.mock("../../api", () => ({
  api: { experimentsDiff: vi.fn(), recentExperiments: vi.fn(), experimentsPaged: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { fetchRunBaselines } from "../../apiRunCode";
import { createQueryClient } from "../../queryClient";
import ComparePage from "../../pages/Compare/ComparePage";
import RunChanges from "../RunChanges";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const WHY = "0.0.1-dev.a has no base commit";
const wrap = (ui: JSX.Element, url = "/") => render(
  <QueryClientProvider client={createQueryClient()}>
    <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
  </QueryClientProvider>,
);

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentsDiff.mockResolvedValue({
    from_verstr: "0.0.1-dev.a", to_verstr: "0.0.2-dev.b", metrics_delta: {}, diff: null, diff_unavailable: WHY,
  });
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
});

describe("a diff the server could not build", () => {
  it("the Changes card shows the reason", async () => {
    (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      previous: { verstr: "0.0.1-dev.a", idx: 1, name: null, status: "succeeded" },
    });
    wrap(<RunChanges ws="w" app="app" verstr="0.0.2-dev.b" baseline={null} onBaseline={() => {}} />);
    expect(await screen.findByText(WHY)).toBeInTheDocument();
  });

  it("the Compare code tab shows the reason", async () => {
    wrap(
      <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>,
      "/ws/w/app/app/compare-runs?tab=code&sel=0.0.1-dev.a&sel=0.0.2-dev.b",
    );
    expect(await screen.findByText(WHY)).toBeInTheDocument();
  });
});
