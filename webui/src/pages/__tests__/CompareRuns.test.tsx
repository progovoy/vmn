import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import type { ExperimentDetail } from "../../types";
import CompareRuns from "../CompareRuns";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const DETAILS: Record<string, ExperimentDetail> = {
  "0.0.1-dev.a": {
    metadata: { verstr: "0.0.1-dev.a", name: "baseline" },
    params: { lr: 0.1, model: "m1" },
    metrics: { loss: 0.3, acc: 0.8 },
    series: {}, patches: {},
    status: { status: "succeeded" } as ExperimentDetail["status"],
  },
  "0.0.2-dev.b": {
    metadata: { verstr: "0.0.2-dev.b" },
    params: { lr: 0.1, model: "m2" },
    metrics: { loss: 0.2, acc: 0.9 },
    series: {}, patches: {},
  },
  "0.0.3-dev.c": {
    metadata: { verstr: "0.0.3-dev.c" },
    params: { lr: 0.1, model: "m3" },
    metrics: { loss: 0.5, acc: 0.7 },
    series: {}, patches: {},
  },
};

const loc = { search: "" };
function Probe() {
  loc.search = useLocation().search;
  return null;
}

function renderPage(search: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs${search}`]}>
        <Probe />
        <Routes>
          <Route path="/ws/:ws/app/:app/compare-runs" element={<CompareRuns />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ALL3 = "?sel=0.0.1-dev.a&sel=0.0.2-dev.b&sel=0.0.3-dev.c";

beforeEach(() => {
  vi.clearAllMocks();
  m.experiment.mockImplementation((_w: string, _a: string, v: string) => Promise.resolve(DETAILS[v]));
  m.metricsSchema.mockResolvedValue({ acc: { goal: "max" } });
});

describe("CompareRuns", () => {
  it("asks for at least two runs", () => {
    renderPage("?sel=0.0.1-dev.a");
    expect(screen.getByText(/select at least two runs/i)).toBeInTheDocument();
  });

  it("shows one column per run, named and linked to its run page", async () => {
    renderPage(ALL3);
    const link = await screen.findByRole("link", { name: "baseline" });
    expect(link).toHaveAttribute("href", "/ws/w/app/my-app/run/0.0.1-dev.a");
    expect(screen.getByRole("link", { name: "0.0.2-dev.b" })).toBeInTheDocument();
    expect(m.experiment).toHaveBeenCalledTimes(3);
  });

  it("puts params and metrics side by side and highlights each metric's best", async () => {
    renderPage(ALL3);
    const lossRow = (await screen.findByText("loss")).closest("tr")!;
    const cells = within(lossRow).getAllByRole("cell");
    expect(cells.map((c) => c.textContent)).toEqual(["loss", "0.3", "0.2", "0.5"]);
    expect(cells[2].className).toContain("best");
    const accRow = screen.getByText("acc").closest("tr")!;
    expect(within(accRow).getByText("0.9").closest("td")!.className).toContain("best");
    expect(within(screen.getByText("model").closest("tr")!).getByText("m3")).toBeInTheDocument();
  });

  it("the only-differing toggle hides equal rows and lives in the URL", async () => {
    renderPage(ALL3);
    await screen.findByText("lr");
    const toggle = screen.getByRole("button", { name: /only differing/i });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.queryByText("lr")).toBeNull());
    expect(screen.getByText("model")).toBeInTheDocument();
    expect(new URLSearchParams(loc.search).get("diff")).toBe("1");
    expect(screen.getByRole("button", { name: /only differing/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("restores the only-differing toggle from the URL", async () => {
    renderPage(`${ALL3}&diff=1`);
    await screen.findByText("model");
    expect(screen.queryByText("lr")).toBeNull();
  });

  it("removes a run from the selection", async () => {
    renderPage(ALL3);
    await screen.findByRole("link", { name: "baseline" });
    fireEvent.click(screen.getByRole("button", { name: "remove 0.0.2-dev.b" }));
    await waitFor(() =>
      expect(new URLSearchParams(loc.search).getAll("sel")).toEqual(["0.0.1-dev.a", "0.0.3-dev.c"]),
    );
    expect(screen.queryByRole("link", { name: "0.0.2-dev.b" })).toBeNull();
  });

  it("links adjacent pairs to the code diff page", async () => {
    renderPage(ALL3);
    await screen.findByRole("link", { name: "baseline" });
    const diffs = screen.getAllByRole("link", { name: /code diff/i });
    expect(diffs).toHaveLength(2);
    expect(diffs[0]).toHaveAttribute(
      "href", "/ws/w/app/my-app/compare?v=0.0.1-dev.a&to=0.0.2-dev.b",
    );
  });

  it("shows a missing value as a dash", async () => {
    m.experiment.mockImplementation((_w: string, _a: string, v: string) =>
      Promise.resolve(v === "0.0.2-dev.b" ? { ...DETAILS[v], params: { lr: 0.1 } } : DETAILS[v]));
    renderPage("?sel=0.0.1-dev.a&sel=0.0.2-dev.b");
    const row = (await screen.findByText("model")).closest("tr")!;
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual(["model", "m1", "—"]);
  });

  it("caps the selection and says so", async () => {
    const many = Array.from({ length: 52 }, (_, i) => `sel=v${i}`).join("&");
    m.experiment.mockImplementation((_w: string, _a: string, v: string) =>
      Promise.resolve({ metadata: { verstr: v }, params: {}, metrics: {}, series: {}, patches: {} }));
    renderPage(`?${many}`);
    expect(await screen.findByText(/first 50/i)).toBeInTheDocument();
    await waitFor(() => expect(m.experiment).toHaveBeenCalledTimes(50));
  });
});
