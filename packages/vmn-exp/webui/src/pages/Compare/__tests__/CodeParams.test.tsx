/** K1/D2 on the Code tab: "What happened" lists metrics only; the params the
 *  diff flags sit in their own "params changed" block. */
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
import type { DiffDelta } from "../../../types";
import ComparePage from "../ComparePage";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const d = (from: number | null, to: number | null, param: boolean): DiffDelta =>
  ({ from, to, goal: param ? null : "min", param });

function renderCode(metrics_delta: Record<string, DiffDelta>) {
  m.experimentsDiff.mockResolvedValue({
    from_verstr: "0.0.1-dev.a", to_verstr: "0.0.2-dev.b", metrics_delta, diff: "",
  });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/ws/w/app/app/compare-runs?tab=code&sel=0.0.1-dev.a&sel=0.0.2-dev.b"]}>
        <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({
    rows: [{ verstr: "0.0.1-dev.a", idx: 1, name: "baseline" }, { verstr: "0.0.2-dev.b", idx: 2, name: null }],
    total: 2,
  });
});

describe("Compare code tab params", () => {
  it("keeps params out of the metric table and lists them in a params changed block", async () => {
    renderCode({ loss: d(1, 0.5, false), lr: d(0.1, null, true), batch_size: d(32, 64, true) });
    const metrics = await screen.findByRole("table", { name: "Metric changes" });
    const metricNames = within(metrics).getAllByRole("row").slice(1).map((r) => r.firstChild?.textContent);
    expect(metricNames).toEqual(["loss"]);
    const block = screen.getByRole("region", { name: "Params changed" });
    expect(within(block).getByRole("heading")).toHaveTextContent(/params changed\s*2/i);
    expect(within(block).getByRole("rowheader", { name: "lr" })).toBeInTheDocument();
    expect(within(block).getByRole("columnheader", { name: /@1 baseline/ })).toBeInTheDocument();
  });

  it("says no metric changed when only params did", async () => {
    renderCode({ lr: d(0.1, 0.01, true) });
    expect(await screen.findByText("No metric changes.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Params changed" })).toBeInTheDocument();
  });
});
