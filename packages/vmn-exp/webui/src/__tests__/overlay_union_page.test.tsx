import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../test-utils";

vi.mock("../apiSeries", () => ({ fetchSeriesBatch: vi.fn(), fetchRunStatuses: vi.fn() }));

import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";
import Overlay from "../pages/Compare/ComparePage";

const batch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;
const statuses = fetchRunStatuses as unknown as ReturnType<typeof vi.fn>;

const curve = (n = 3) => Array.from({ length: n }, (_, i) => ({ step: i, value: 1 - i * 0.1, ts: null }));

const SERIES: Record<string, Record<string, ReturnType<typeof curve>>> = {
  "0.0.1-dev.a": { loss: curve(), acc: curve() },
  "0.0.1-dev.b": { loss: curve() },
  "0.0.1-dev.o": {},
};
const ROWS = {
  "0.0.1-dev.a": { verstr: "0.0.1-dev.a", idx: 1, name: "alpha", kind: "inner" },
  "0.0.1-dev.b": { verstr: "0.0.1-dev.b", idx: 2, name: "beta", kind: "inner" },
  "0.0.1-dev.o": {
    verstr: "0.0.1-dev.o", idx: 36, name: "lr_layers_grid", kind: "outer",
    children: ["0.0.1-dev.a", "0.0.1-dev.b"],
  },
};

function renderOverlay(runs: string[], series = SERIES, rows: Record<string, object> = ROWS) {
  batch.mockImplementation((_w: string, _a: string, vs: string[]) => Promise.resolve({
    series: Object.fromEntries(vs.map((v) => [v, series[v]])), missing: [],
  }));
  statuses.mockResolvedValue(rows);
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/w/app/app/compare-runs?${runs.map((r) => `sel=${r}`).join("&")}`]}>
      <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<Overlay />} /></Routes>
    </MemoryRouter>,
  );
}

const chartTitles = () => [...document.querySelectorAll(".card .section-title")].map((e) => e.textContent);

beforeEach(() => vi.clearAllMocks());

describe("Overlay page with partial metric coverage", () => {
  it("charts the union of metrics instead of an empty state", async () => {
    renderOverlay(["0.0.1-dev.a", "0.0.1-dev.b", "0.0.1-dev.o"]);
    await screen.findByText(/No curves:/);
    expect(chartTitles()).toEqual(["acc", "loss"]);
    expect(screen.queryByText(/No shared metrics/)).toBeNull();
  });

  it("names the curveless sweep run and links to its trials", async () => {
    renderOverlay(["0.0.1-dev.a", "0.0.1-dev.o"]);
    expect(await screen.findByText(
      "No curves: @36 lr_layers_grid (sweep run; its trials log the curves)",
    )).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /overlay its 2 trials/ });
    // Plan 20 M3: straight to the Compare page, not through the old overlay redirect.
    expect(link.getAttribute("href")).toBe("/ws/w/app/app/compare-runs?tab=curves&sel=0.0.1-dev.a&sel=0.0.1-dev.b");
  });

  it("names each sweep in its trials link when several are curveless", async () => {
    const rows = { ...ROWS, "0.0.1-dev.k": {
      verstr: "0.0.1-dev.k", idx: 24, name: "kfold-cv", kind: "outer", children: ["0.0.1-dev.b"],
    } };
    renderOverlay(["0.0.1-dev.a", "0.0.1-dev.o", "0.0.1-dev.k"], { ...SERIES, "0.0.1-dev.k": {} }, rows);
    expect(await screen.findByRole("link", { name: "overlay @36's 2 trials" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "overlay @24's 1 trial" })).toBeInTheDocument();
  });

  it("leaves curveless runs out of the legend", async () => {
    renderOverlay(["0.0.1-dev.a", "0.0.1-dev.o"]);
    await screen.findByText(/No curves:/);
    // Plan 20 M2: legend entries read @N name, the verstr in their title.
    expect(screen.getByRole("button", { name: "@1 alpha" })).toHaveAttribute("title", "0.0.1-dev.a");
    expect(screen.queryByRole("button", { name: "@36 lr_layers_grid" })).toBeNull();
  });

  it("keeps the empty state when no selected run has a curve", async () => {
    renderOverlay(["0.0.1-dev.o"]);
    expect(await screen.findByText(/None of the selected runs has series data/)).toBeInTheDocument();
    expect(chartTitles()).toEqual([]);
    expect(screen.queryByText(/No curves:/)).toBeNull();
    expect(screen.getByRole("link", { name: /overlay its 2 trials/ })).toBeInTheDocument();
  });
});
