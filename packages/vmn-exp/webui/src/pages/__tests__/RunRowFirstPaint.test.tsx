import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), action: vi.fn(), job: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../apiSeries", async (orig) => ({
  ...(await orig<typeof import("../../apiSeries")>()), fetchRunStatuses: vi.fn(),
}));

import { api } from "../../api";
import { fetchRunStatuses } from "../../apiSeries";
import { createQueryClient } from "../../queryClient";
import type { ExperimentRow } from "../../types";
import Run from "../Run";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const statuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;
const VERSTR = "2.0.251-dev.33775bd.0000000.trial.ex1";

const indexRow: ExperimentRow = {
  idx: 9, verstr: VERSTR, code_verstr: VERSTR, timestamp: "2026-01-01T12:00:00Z",
  note: "index note", branch: "feat/index", base_version: "2.0.251",
  params: { model: "ridge" }, metrics: { "cv0.r2": 0.41 }, status: "running",
  duration_sec: 125, children: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
});

describe("Run first paint on a direct link", () => {
  it("paints the first card from the index row lookup while the detail loads", async () => {
    statuses.mockResolvedValue({ [VERSTR]: indexRow });
    m.experiment.mockImplementation(() => new Promise(() => {}));
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${VERSTR}`]}>
          <Routes>
            <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: VERSTR })).toBeInTheDocument();
    expect(screen.getByText("index note")).toBeInTheDocument();
    expect(screen.getByText("feat/index")).toBeInTheDocument();
    expect(document.querySelector(".status-pill.running")).not.toBeNull();
    expect(screen.getByText("0.41")).toBeInTheDocument();
    expect(screen.getByText("ridge")).toBeInTheDocument();
    expect(m.experiment).toHaveBeenCalledTimes(1);
  });
});
