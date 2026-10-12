import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import type { ExperimentDetail } from "../../types";
import CompareRuns from "../CompareRuns";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

/** A verstr with mixed case hex, like a real dev version. */
const VERSTR = "0.0.1-dev.a3Bf";

const DETAIL: ExperimentDetail = {
  metadata: { verstr: VERSTR },
  params: { lr: 0.1 },
  metrics: { loss: 0.5 },
  series: {},
  patches: {},
  status: { status: "succeeded" } as ExperimentDetail["status"],
};

const VERSTR2 = "0.0.2-dev.c4De";
const DETAIL2: ExperimentDetail = {
  metadata: { verstr: VERSTR2 },
  params: { lr: 0.2 },
  metrics: { loss: 0.3 },
  series: {},
  patches: {},
};

function renderPage(search: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs${search}`]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/compare-runs" element={<CompareRuns />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.experiment.mockImplementation((_w: string, _a: string, v: string) => {
    if (v === VERSTR) return Promise.resolve(DETAIL);
    if (v === VERSTR2) return Promise.resolve(DETAIL2);
    return Promise.reject(new Error("not found"));
  });
  m.metricsSchema.mockResolvedValue({});
});

describe("Compare header case preservation (A4)", () => {
  it("compare header text equals verstr exactly without uppercase transformation", async () => {
    renderPage(`?sel=${VERSTR}&sel=${VERSTR2}`);
    // Wait for runs to render
    const link = await screen.findByRole("link", { name: VERSTR });
    // The verstr link text should preserve exact case
    expect(link.textContent).toBe(VERSTR);

    const link2 = screen.getByRole("link", { name: VERSTR2 });
    expect(link2.textContent).toBe(VERSTR2);
  });

  it("section labels (metrics, params) stay uppercase via a dedicated class", async () => {
    renderPage(`?sel=${VERSTR}&sel=${VERSTR2}`);
    await screen.findByRole("link", { name: VERSTR });

    // Section headers "metrics" and "params" should have a class for uppercase
    const sectionHeaders = document.querySelectorAll(".compare-section th");
    expect(sectionHeaders.length).toBeGreaterThan(0);
    for (const th of sectionHeaders) {
      expect(th.classList.contains("label-caps")).toBe(true);
    }
  });
});
