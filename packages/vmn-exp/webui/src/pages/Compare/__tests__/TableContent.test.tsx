/** M2 on the Table tab: `@N name` run headers (verstr in the title, a copy
 *  button), Only differing on by default, Metrics (no params, D2) and Params
 *  sections with a "changed" count, best only for a metric with a goal (D1). */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), experimentsPaged: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../../api";
import { createQueryClient } from "../../../queryClient";
import type { ExperimentDetail } from "../../../types";
import ComparePage from "../ComparePage";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const run = (verstr: string, idx: number, name: string | null, params: Record<string, unknown>,
  metrics: ExperimentDetail["metrics"], extra: Partial<ExperimentDetail> = {}): ExperimentDetail => ({
  metadata: { verstr, ...(name ? { name } : {}) }, idx, name, params, metrics, series: {}, patches: {},
  status: { status: "succeeded" } as ExperimentDetail["status"], ...extra,
});

const DETAILS: Record<string, ExperimentDetail> = {
  "0.0.1-dev.a": run("0.0.1-dev.a", 1, "baseline",
    { lr: 0.1, batch: 32, model: "m1" },
    { lr: 0.1, batch: 32, loss: 0.3, throughput: 10, acc: 0.8 },
    { metric_summary: { loss: { last: 0.3, min: 0.3, max: 1, first: 1, mean: 0.5 } } }),
  "0.0.2-dev.b": run("0.0.2-dev.b", 2, null,
    { lr: 0.1, batch: 64, model: "m1" },
    { lr: 0.1, batch: 64, loss: 0.2, throughput: 20, acc: 0.8 }),
};

const loc = { search: "" };
function Probe() {
  loc.search = useLocation().search;
  return null;
}

function renderTable(extra = "") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs?tab=table&sel=0.0.1-dev.a&sel=0.0.2-dev.b${extra}`]}>
        <Probe />
        <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const section = (name: RegExp) => screen.getByRole("rowheader", { name });
const rowKeys = () => screen.getAllByRole("row")
  .map((r) => r.querySelector("td.compare-key")?.textContent)
  .filter(Boolean);

beforeEach(() => {
  vi.clearAllMocks();
  m.experiment.mockImplementation((_w: string, _a: string, v: string) => Promise.resolve(DETAILS[v]));
  m.metricsSchema.mockResolvedValue({});
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
});

describe("Compare table run headers", () => {
  it("read @N name, with the verstr in the title", async () => {
    renderTable();
    const named = await screen.findByRole("link", { name: "@1 baseline" });
    expect(named).toHaveAttribute("title", "0.0.1-dev.a");
    expect(screen.getByRole("link", { name: "@2" })).toHaveAttribute("title", "0.0.2-dev.b");
  });

  it("copy the verstr from a button in each header", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderTable();
    await screen.findByRole("link", { name: "@1 baseline" });
    const head = screen.getByRole("link", { name: "@1 baseline" }).closest("th")!;
    fireEvent.click(within(head).getByRole("button", { name: "copy 0.0.1-dev.a" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("0.0.1-dev.a"));
  });

  it("are marked as identifiers, so the th caps never apply", async () => {
    renderTable();
    const head = (await screen.findByRole("link", { name: "@1 baseline" })).closest("th")!;
    expect(head.className).toContain("compare-ident");
  });
});

describe("Compare table Only differing", () => {
  it("is on by default and hides equal rows", async () => {
    renderTable();
    await screen.findByRole("link", { name: "@1 baseline" });
    expect(screen.getByRole("button", { name: /only differing/i })).toHaveAttribute("aria-pressed", "true");
    expect(rowKeys()).not.toContain("model");
    expect(rowKeys()).toContain("batch");
  });

  it("turns off into ?diff=0 and then shows every row", async () => {
    renderTable();
    await screen.findByRole("link", { name: "@1 baseline" });
    fireEvent.click(screen.getByRole("button", { name: /only differing/i }));
    await waitFor(() => expect(rowKeys()).toContain("model"));
    expect(new URLSearchParams(loc.search).get("diff")).toBe("0");
    expect(screen.getByRole("button", { name: /only differing/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("stays off from ?diff=0", async () => {
    renderTable("&diff=0");
    await screen.findByRole("link", { name: "@1 baseline" });
    expect(rowKeys()).toContain("model");
  });
});

describe("Compare table sections", () => {
  it("lists params folded into metrics only under Params (D2)", async () => {
    renderTable("&diff=0");
    await screen.findByRole("link", { name: "@1 baseline" });
    const metricRows = screen.getAllByRole("row").filter((r) => r.dataset.section === "metrics")
      .map((r) => r.querySelector("td.compare-key")!.textContent);
    expect(metricRows).toEqual(["acc", "loss", "throughput"]);
    const paramRows = screen.getAllByRole("row").filter((r) => r.dataset.section === "params")
      .map((r) => r.querySelector("td.compare-key")!.textContent);
    expect(paramRows).toEqual(["batch", "lr", "model"]);
  });

  it("titles the sections Metrics and Params, counting the params that changed", async () => {
    renderTable();
    await screen.findByRole("link", { name: "@1 baseline" });
    expect(section(/^metrics$/i)).toBeInTheDocument();
    expect(section(/^params/i)).toHaveTextContent("1 of 3 changed");
  });

  it("marks a best value only for a metric with a goal (D1)", async () => {
    renderTable();
    await screen.findByRole("link", { name: "@1 baseline" });
    const cells = (key: string) => within(rowOf(key)).getAllByRole("cell").slice(1);
    expect(cells("loss")[1].className).toContain("best");
    expect(cells("throughput").some((c) => c.className.includes("best"))).toBe(false);
  });
});

function rowOf(key: string) {
  return screen.getAllByRole("row").find((r) => r.querySelector("td.compare-key")?.textContent === key)!;
}

describe("compare.css", () => {
  it("lifts the th caps off identifier headers (D3)", async () => {
    const css = (await import("../compare.css?raw")).default;
    expect(css).toMatch(/\.compare-ident[^{]*\{[^}]*text-transform:\s*none/);
  });
});
