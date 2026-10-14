/** The job's Charts tab (plan 23 W4): every run of the job from
 *  `experiments-columns?scope=`, the chart and its axes in the URL, brushing
 *  that filters the Runs tab, the top-K curves and boxes per param value. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("uplot", async () => await import("../../../components/__tests__/fakeUPlot"));
vi.mock("../../../apiJobCharts", () => ({ jobFacets: vi.fn(), jobColumns: vi.fn(), jobTopRuns: vi.fn() }));
vi.mock("../../../components/OverlayChart", () => ({
  default: ({ verstrs, keys }: { verstrs: string[]; keys: string[] }) => (
    <div data-testid="overlay">{keys.join(",")}: {verstrs.join(",")}</div>
  ),
}));

import { jobColumns, jobFacets, jobTopRuns } from "../../../apiJobCharts";
import { enableCanvas, instances, resetInstances } from "../../../components/__tests__/fakeUPlot";
import type { JobPageSummary } from "../../../apiJob";
import type { ExperimentColumns, ExperimentFacets } from "../../../types";
import JobCharts from "../JobCharts";
import { JOB, jobSummaryFixture } from "./jobFixture";

const FACETS: ExperimentFacets = {
  branches: ["main"], metric_keys: ["val_loss", "acc"], param_keys: ["lr", "opt", "seed"], tag_keys: [],
  param_values: { lr: 3, opt: 2, seed: 1 }, parented: 3, total: 3,
};

/** Whatever keys are asked for, from three runs. */
function columns(keys: string[]): ExperimentColumns {
  const all: Record<string, (number | string | null)[]> = {
    "metrics.val_loss": [0.5, 0.3, 0.7], "metrics.acc": [0.8, 0.9, 0.7],
    "params.lr": [0.01, 0.001, 0.1], "params.opt": ["adam", "sgd", "adam"], "params.seed": [1, 1, 1],
    status: ["succeeded", "failed", "succeeded"], name: ["t1", "t2", "t3"],
  };
  return {
    verstrs: ["r1", "r2", "r3"], idx: [1, 2, 3], total: 3,
    columns: Object.fromEntries(keys.map((k) => [k, all[k] ?? [null, null, null]])),
  };
}

function Where() {
  const { search } = useLocation();
  return <output data-testid="where">{search}</output>;
}
const lastColumnsCall = () => {
  const calls = vi.mocked(jobColumns).mock.calls;
  return calls[calls.length - 1];
};
const where = () =>new URLSearchParams(screen.getByTestId("where").textContent ?? "");

function renderCharts(search = "", summary: JobPageSummary = jobSummaryFixture()) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${JOB}?tab=charts${search}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr"
          element={<><JobCharts ws="test" app="my-app" summary={summary} /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

const originalMatchMedia = window.matchMedia;
const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  vi.mocked(jobFacets).mockResolvedValue(FACETS);
  vi.mocked(jobColumns).mockImplementation(async (_ws, _app, _v, keys) => columns(keys));
  vi.mocked(jobTopRuns).mockResolvedValue([]);
});
afterEach(() => {
  window.matchMedia = originalMatchMedia;
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("the job Charts tab", () => {
  it("opens on the scatter of the main metric against the first varying param, by status", async () => {
    renderCharts();
    const fig = await screen.findByRole("figure", { name: /val_loss against lr/ });
    expect(within(fig).getByText(/3 runs/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scatter" })).toHaveAttribute("aria-pressed", "true");
    const keys = lastColumnsCall()[3];
    expect(keys).toEqual(expect.arrayContaining(["params.lr", "metrics.val_loss", "status", "name"]));
    expect(lastColumnsCall().slice(0, 3)).toEqual(["test", "my-app", JOB]);
    const legend = screen.getByRole("list", { name: /colour/i });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["failed1", "succeeded2"]);
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
  });

  it("keeps the chart and its axes in the URL", async () => {
    renderCharts();
    const color = await screen.findByRole("combobox", { name: "Colour by" });
    expect([...(color as HTMLSelectElement).options].map((o) => o.value)).toEqual(["status", "lr", "opt"]);
    fireEvent.change(color, { target: { value: "opt" } });
    await waitFor(() => expect(where().get("color")).toBe("opt"));
    fireEvent.change(screen.getByRole("combobox", { name: "Y" }),{ target: { value: "acc" } });
    await waitFor(() => expect(where().get("y")).toBe("acc"));
    expect(where().get("x")).toBe("lr");
    fireEvent.click(screen.getByRole("button", { name: "Parallel" }));
    await waitFor(() => expect(where().get("chart")).toBe("parallel"));
  });

  it("turns a parallel-coordinates brush into a Runs-tab filter", async () => {
    const { container } = renderCharts("&chart=parallel");
    await screen.findByRole("figure", { name: /Parallel coordinates/ });
    const area = container.querySelectorAll("[data-testid='brush-area']")[0];
    fireEvent.mouseDown(area, { clientY: 20 });
    fireEvent.mouseMove(area, { clientY: 150 });
    fireEvent.mouseUp(area, { clientY: 150 });
    const link = await screen.findByRole("link", { name: "Show 2 brushed runs in Runs" });
    const href = new URLSearchParams(link.getAttribute("href")!.split("?")[1]);
    expect(href.get("tab")).toBe("runs");
    expect(href.get("q")).toBe("metrics.val_loss >= 0.5 and metrics.val_loss <= 0.7");
  });

  it("overlays the summary's top runs for K up to 10", async () => {
    renderCharts("&chart=curves&k=5");
    expect(await screen.findByTestId("overlay")).toHaveTextContent("val_loss: 0.0.2-dev.t1903,0.0.2-dev.t12");
    expect(jobTopRuns).not.toHaveBeenCalled();
  });

  it("asks the scoped list for the top 20 when the summary's 10 are not all", async () => {
    const top = Array.from({ length: 10 }, (_, i) => ({ verstr: `t${i}`, idx: i, name: null, status: "succeeded" as const, value: i }));
    vi.mocked(jobTopRuns).mockResolvedValue(Array.from({ length: 20 }, (_, i) => `k${i}`));
    renderCharts("&chart=curves", jobSummaryFixture({ top }));
    expect(await screen.findByTestId("overlay")).toHaveTextContent("k19");
    expect(jobTopRuns).toHaveBeenCalledWith("test", "my-app", JOB, "val_loss", 20);
    expect(screen.getByRole("button", { name: "Top 20" })).toHaveAttribute("aria-pressed", "true");
  });

  it("boxes the metric per value of a param, with a table for screen readers", async () => {
    renderCharts("&chart=bypar&x=opt");
    const fig = await screen.findByRole("figure", { name: /val_loss by opt/ });
    const table = within(fig).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows[0]).toMatch(/^adam2/);
    expect(rows[1]).toMatch(/^sgd1/);
    expect(lastColumnsCall()[3]).toEqual(["metrics.val_loss", "params.opt"]);
  });

  it("says why a chart is empty, and shows a failed load", async () => {
    vi.mocked(jobColumns).mockResolvedValueOnce({ verstrs: [], idx: [], total: 0, columns: {} });
    renderCharts();
    expect(await screen.findByText(/No run of this job has both lr and val_loss yet/)).toBeInTheDocument();
    vi.mocked(jobColumns).mockRejectedValue(new Error("boom"));
    fireEvent.click(screen.getByRole("button", { name: "By param" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("has nothing to chart before any run logs a metric", async () => {
    vi.mocked(jobFacets).mockResolvedValue({ ...FACETS, metric_keys: [] });
    renderCharts("", jobSummaryFixture({ metrics: {}, metric: null }));
    expect(await screen.findByText(/No run of this job has logged a metric yet/)).toBeInTheDocument();
    expect(jobColumns).not.toHaveBeenCalled();
  });
});
