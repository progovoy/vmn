/** Plan 23 W2: the job's Overview tab, all from its summary. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));

import { jobFailures, jobImportance } from "../../../apiJob";
import JobOverview from "../JobOverview";
import { clusterFixture, failuresFixture, JOB, jobSummaryFixture } from "./jobFixture";
import type { JobSummary } from "../../../apiJob";

const BASE = "/ws/test/app/my-app";

function renderOverview(summary: JobSummary = jobSummaryFixture()) {
  return renderWithClient(
    <MemoryRouter><JobOverview ws="test" app="my-app" summary={summary} /></MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(jobFailures).mockResolvedValue(failuresFixture());
  vi.mocked(jobImportance).mockResolvedValue([
    { param: "lr", importance: 0.8, correlation: -0.5, spearman: -0.4, kind: "numeric", n: 1409 },
    { param: "layers", importance: 0.2, correlation: 0.1, spearman: 0.1, kind: "numeric", n: 1409 },
  ]);
});

describe("job overview", () => {
  it("shows the KPI tiles, the best one linked to its run", () => {
    renderOverview();
    const tiles = screen.getByRole("list", { name: "Job KPIs" });
    expect(within(tiles).getByText("1,412")).toBeInTheDocument();
    expect(within(tiles).getByText("of 2,000")).toBeInTheDocument();
    expect(within(tiles).getByText("1.5%")).toBeInTheDocument();
    expect(within(tiles).getByText("3 runs")).toBeInTheDocument();
    expect(within(tiles).getByRole("link", { name: /best val_loss/ }))
      .toHaveAttribute("href", `${BASE}/run/0.0.2-dev.t1903`);
  });

  it("charts progress over time and completions per minute on their own axes", () => {
    renderOverview();
    expect(screen.getByRole("img", { name: /Progress over time: 60 started, 30 succeeded, 1 failed, 29 running/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Completions per minute: latest 31/ })).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Status legend" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["running", "succeeded", "failed"]);
  });

  it("says so when no run has started yet", () => {
    renderOverview(jobSummaryFixture({ timeline: { bucket_sec: 60, start: null, buckets: [] } }));
    expect(screen.getByText("No run has started yet.")).toBeInTheDocument();
  });

  it("draws the main metric's distribution with p10/p50/p90, another metric on pick", () => {
    renderOverview();
    expect(screen.getByRole("img", { name: /val_loss over 1,409 runs: p10 0.2, p50 0.38, p90 0.7/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Distribution metric"), { target: { value: "acc" } });
    expect(screen.getByRole("img", { name: /acc over 1,409 runs: p10 0.3, p50 0.6, p90 0.9/ })).toBeInTheDocument();
  });

  it("lists the top runs with links and a way to all of them", () => {
    renderOverview();
    const top = screen.getByRole("table", { name: "Top runs on val_loss" });
    expect(within(top).getByRole("link", { name: "@1903 t1903" })).toHaveAttribute("href", `${BASE}/run/0.0.2-dev.t1903`);
    expect(within(top).getByRole("link", { name: "@12" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show all in Runs" })).toHaveAttribute("href", `${BASE}/run/${JOB}?tab=runs`);
  });

  it("says no goal is declared when the job's metrics aren't ranked", () => {
    renderOverview(jobSummaryFixture({ ranked: false, top: [] }));
    const card = screen.getByRole("region", { name: "Top runs on val_loss" });
    expect(card).toHaveTextContent(
      "No goal declared for val_loss — runs aren't ranked. Declare one with experiment.metrics.val_loss.goal or run.define_metric(goal=...)",
    );
  });

  it("says so when no run of the job logged a metric", () => {
    renderOverview(jobSummaryFixture({ metric: null, metrics: {}, top: [] }));
    expect(screen.getByRole("region", { name: "Distribution" })).toHaveTextContent("No run in this job logged a metric yet");
    expect(screen.getByRole("region", { name: "Top runs" })).toHaveTextContent("No run in this job logged a metric yet");
  });

  it("names the top failure clusters, each linking to the Failures tab", async () => {
    renderOverview();
    const link = await screen.findByRole("link", { name: /CUDA out of memory/ });
    expect(link).toHaveAttribute("href", `${BASE}/run/${JOB}?tab=failures`);
    expect(screen.getByText("2 runs · 67%")).toBeInTheDocument();
  });

  it("is glad when nothing failed", async () => {
    vi.mocked(jobFailures).mockResolvedValue({ total_failed: 0, clusters: [] });
    renderOverview();
    expect(await screen.findByText("No failures.")).toBeInTheDocument();
  });

  it("caps the failure clusters at three", async () => {
    vi.mocked(jobFailures).mockResolvedValue(failuresFixture(
      ["a", "b", "c", "d"].map((l) => clusterFixture({ sig: l, label: `cluster ${l}` })),
    ));
    renderOverview();
    await screen.findByText("cluster a");
    expect(screen.queryByText("cluster d")).toBeNull();
  });

  it("shows the params that matter for a sweep, scoped to the job", async () => {
    renderOverview(jobSummaryFixture({ sweep: true }));
    expect(await screen.findByText("lr")).toBeInTheDocument();
    expect(jobImportance).toHaveBeenCalledWith("test", "my-app", JOB, "val_loss");
    expect(screen.getByRole("meter", { name: "lr importance" })).toHaveAttribute("aria-valuenow", "0.8");
  });

  it("asks no importance of a job that is not a sweep", async () => {
    renderOverview();
    await waitFor(() => expect(jobFailures).toHaveBeenCalled());
    expect(jobImportance).not.toHaveBeenCalled();
    expect(screen.queryByText("Params that matter")).toBeNull();
  });
});
