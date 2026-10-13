/** Plan 20 B5 (D5): the run page answers its questions in order — what it is,
 *  how it went, what changed — and keeps the details in collapsed sections. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), meta: vi.fn(), workspaces: vi.fn(), experimentsDiff: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (name: string) => name.replaceAll("/", "-"),
  artifactUrl: () => "",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn(), metricKeys: vi.fn() }));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));
vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));
vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { listComments: vi.fn(), reportsUsing: vi.fn() },
}));
vi.mock("../../components/TrainingCurves", () => ({
  default: () => <div className="card"><h2>Training curves</h2></div>,
}));

import { api } from "../../api";
import { apiReports } from "../../apiReports";
import { fetchRunBaselines } from "../../apiRunCode";
import { DISCLOSURE_KEY } from "../../components/Disclosure";
import { fullDetail, renderRunPage, runStatus, sectionHeadings } from "./runPageFixture";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const reports = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;
const toggle = (name: string) => screen.getByRole("button", { name });
const region = (name: string) => screen.getByRole("region", { name });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("tail"))));
  mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  mockedApi.meta.mockResolvedValue({ read_only: true });
  mockedApi.workspaces.mockResolvedValue([]);
  mockedApi.experimentsDiff.mockResolvedValue({ from_verstr: "x", to_verstr: "y", metrics_delta: {}, diff: "" });
  (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
  reports.listComments.mockResolvedValue({ comments: [] });
  reports.reportsUsing.mockResolvedValue({ reports: [] });
  mockedApi.experiment.mockResolvedValue(fullDetail());
});

describe("Run page section order (D5)", () => {
  it("orders a failed outer run's sections from the failure down to the details", async () => {
    mockedApi.experiment.mockResolvedValue(fullDetail({
      status: runStatus({
        status: "failed", exit_code: 1, kind: "outer", tree_status: "failed", children: ["c1"],
        error_summary: "CUDA out of memory",
        fleet: { expected: 1, counts: { failed: 1 }, children: [{ verstr: "c1", status: "failed", progress: null, progress_total: null }] },
      }),
      output_tail: { lines: ["CUDA out of memory"], truncated: false },
    }));
    renderRunPage();
    await screen.findByText("Training curves");
    await waitFor(() => expect(sectionHeadings()).toEqual([
      "Error", "Training curves", "Changes", "Fleet", "Parameters", "Metrics",
      "Similar runs", "Lineage", "Output", "Artifacts",
      "Status details", "Log", "Environment", "Media", "Comments",
    ]));
  });

  it("puts the status pill, @N and base version in the header", async () => {
    renderRunPage();
    await screen.findByText("Training curves");
    const head = document.querySelector(".run-status-line") as HTMLElement;
    expect(head.querySelector(".status-pill")?.className).toContain("succeeded");
    expect(head).toHaveTextContent("@7");
    expect(head).toHaveTextContent("base 0.0.1");
  });

  it("shows an outer run's tree and its finished inner count, never its own `created`", async () => {
    mockedApi.experiment.mockResolvedValue(fullDetail({
      status: runStatus({
        status: "created", kind: "outer", tree_status: "succeeded", children: ["c1", "c2"],
        fleet: { expected: 2, counts: { succeeded: 2 }, children: [] },
      }),
    }));
    renderRunPage();
    await screen.findByText("Training curves");
    const head = document.querySelector(".run-status-line") as HTMLElement;
    expect(head.querySelector(".status-pill")?.className).toContain("succeeded");
    expect(head).toHaveTextContent("2/2 inner");
    expect(head).not.toHaveTextContent("created");
  });

  it("lists params under Params only, never as metrics (D2)", async () => {
    renderRunPage();
    await screen.findByText("Training curves");
    expect(screen.queryByTestId("metric-value-lr")).toBeNull();
    expect(screen.getByTestId("metric-value-loss")).toBeInTheDocument();
  });
});

describe("Run page disclosures (D5)", () => {
  it("collapses the log, its summary row holding the last 10 entries", async () => {
    renderRunPage();
    const log = await waitFor(() => region("Log"));
    expect(toggle("Log")).toHaveAttribute("aria-expanded", "false");
    const preview = within(log).getAllByRole("listitem").map((li) => li.textContent);
    expect(preview).toHaveLength(10);
    expect(preview[0]).toContain("entry-4");
    expect(preview[9]).toContain("entry-13");
    fireEvent.click(toggle("Log"));
    expect(within(region("Log")).getAllByRole("listitem")).toHaveLength(14);
  });

  it("collapses Status details and Environment, keeping the heartbeat of a finished run in the details", async () => {
    renderRunPage();
    await waitFor(() => region("Status details"));
    expect(toggle("Status details")).toHaveAttribute("aria-expanded", "false");
    expect(toggle("Environment")).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".run-status-line")).not.toHaveTextContent("heartbeat");
    fireEvent.click(toggle("Status details"));
    const details = region("Status details");
    expect(within(details).getByText("heartbeat")).toBeVisible();
    expect(within(details).getByText("gpu0")).toBeVisible();
    expect(within(details).getByText("python train.py")).toBeVisible();
  });

  it("opens Media when there is any, and Comments only when there are some", async () => {
    reports.listComments.mockResolvedValue({
      comments: [{ id: "1", text: "nice", resolved: false, deleted: false }],
    });
    renderRunPage();
    await waitFor(() => region("Media"));
    expect(toggle("Media")).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(toggle("Comments")).toHaveAttribute("aria-expanded", "true"));
  });

  it("keeps Comments closed without any", async () => {
    renderRunPage();
    await waitFor(() => region("Comments"));
    await waitFor(() => expect(reports.listComments).toHaveBeenCalled());
    expect(toggle("Comments")).toHaveAttribute("aria-expanded", "false");
  });

  it("remembers an opened section for the next run page", async () => {
    const first = renderRunPage();
    await waitFor(() => region("Log"));
    fireEvent.click(toggle("Log"));
    expect(JSON.parse(localStorage.getItem(DISCLOSURE_KEY)!)).toMatchObject({ "run-log": true });
    first.unmount();
    renderRunPage();
    await waitFor(() => expect(toggle("Log")).toHaveAttribute("aria-expanded", "true"));
  });
});
