import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "../../queryClient";

// --- Compare (code diff) page tests ---

vi.mock("../../api", () => ({
  api: {
    experimentsDiff: vi.fn(),
    metricsSchema: vi.fn(),
    recentExperiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experiment: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import Compare from "../Compare/ComparePage";
import CompareRuns from "../Compare/ComparePage";
import type { ExperimentDetail } from "../../types";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderCompare(search = "?tab=code&sel=a&sel=b") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs${search}`]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/compare-runs" element={<Compare />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const loc = { search: "" };
function Probe() {
  loc.search = useLocation().search;
  return null;
}

function renderCompareRuns(search: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs?tab=table&${search.slice(1)}`]}>
        <Probe />
        <Routes>
          <Route path="/ws/:ws/app/:app/compare-runs" element={<CompareRuns />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.recentExperiments.mockResolvedValue([]);
});

describe("Compare 422 error", () => {
  it("shows the reason and keeps run pickers usable when the API returns 422", async () => {
    const err = Object.assign(
      new Error("Failed to materialize snapshots for diff"),
      {
        status: 422,
        body: {
          detail: "Failed to materialize snapshots for diff",
          reason: "code_missing",
        },
      },
    );
    m.experimentsDiff.mockRejectedValue(err);
    renderCompare();
    await waitFor(() => {
      expect(screen.getByText(/code_missing/i)).toBeInTheDocument();
    });
    // The run pickers should still be present (not blanked)
    expect(screen.getAllByRole("combobox").length).toBeGreaterThan(0);
  });

  it("says in words why a 422 diff is unavailable, the reason code beside it", async () => {
    m.experimentsDiff.mockRejectedValue(Object.assign(new Error("Failed to materialize"), {
      status: 422, body: { reason: "code_missing" },
    }));
    renderCompare();
    expect(await screen.findByText(/code object is missing from the store/)).toBeInTheDocument();
  });

  it("shows a generic error message for non-422 failures", async () => {
    m.experimentsDiff.mockRejectedValue(new Error("Internal server error"));
    renderCompare();
    await waitFor(() => {
      expect(screen.getByText(/internal server error/i)).toBeInTheDocument();
    });
  });
});

describe("CompareRuns unknown ref", () => {
  const DETAILS: Record<string, ExperimentDetail> = {
    "0.0.1-dev.a": {
      metadata: { verstr: "0.0.1-dev.a", name: "baseline" },
      params: { lr: 0.1 },
      metrics: { loss: 0.3 },
      series: {}, patches: {},
      status: { status: "succeeded" } as ExperimentDetail["status"],
    },
    "0.0.2-dev.b": {
      metadata: { verstr: "0.0.2-dev.b" },
      params: { lr: 0.2 },
      metrics: { loss: 0.2 },
      series: {}, patches: {},
    },
  };

  it("shows a not-found chip for an unknown ref, no column, excluded from count", async () => {
    m.experiment.mockImplementation((_w: string, _a: string, v: string) => {
      if (DETAILS[v]) return Promise.resolve(DETAILS[v]);
      return Promise.reject(Object.assign(new Error("not found"), { status: 404 }));
    });
    renderCompareRuns("?sel=0.0.1-dev.a&sel=unknown-ref&sel=0.0.2-dev.b");
    // The unknown ref should show a "not found" chip
    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/unknown-ref/)).toBeInTheDocument();
    // Should have a remove button for the unknown ref
    expect(screen.getByRole("button", { name: /remove unknown-ref/i })).toBeInTheDocument();
    // The count should say "2 runs" not "3 runs"
    expect(screen.getByText(/2 runs/i)).toBeInTheDocument();
    // The loaded runs should still have columns
    expect(screen.getByRole("link", { name: "baseline" })).toBeInTheDocument();
  });
});
