/** Plan 20 §6 flow acceptance on the run page: F3 (the diff in one click),
 *  F4 (a copied restore in two), F6 (the failure's output first).
 *  F1 is LeaderboardAttention.test, F5 Compare/ComparePage.test, F7's tree
 *  pill RunLayout.test + OuterTreeStatus.test. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

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
import { vmnExpCommand } from "../../shell/cliCommands";
import { RUN, fullDetail, renderRunPage, runStatus, sectionHeadings } from "./runPageFixture";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const reports = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;
const writeText = vi.fn();
const DIFF = ["diff --git a/train.py b/train.py", "@@ -1 +1 @@", "-lr = 0.1", "+lr = 0.01"].join("\n");

/** Clicks made by a flow, so each test can state its budget. */
let clicks = 0;
const click = (el: HTMLElement) => { clicks += 1; fireEvent.click(el); };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  clicks = 0;
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("tail"))));
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
  mockedApi.meta.mockResolvedValue({ version: "1", read_only: false });
  mockedApi.workspaces.mockResolvedValue([{ name: "test", kind: "git", path: "/r" }]);
  mockedApi.experimentsDiff.mockResolvedValue({ from_verstr: "v-prev", to_verstr: RUN, metrics_delta: {}, diff: DIFF });
  (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    previous: { verstr: "v-prev", idx: 6, name: null, status: "succeeded" },
  });
  reports.listComments.mockResolvedValue({ comments: [] });
  reports.reportsUsing.mockResolvedValue({ reports: [] });
  mockedApi.experiment.mockResolvedValue(fullDetail());
});

describe("run page flows (plan 20 §6)", () => {
  it("F3: one click from the run to its diff against the default baseline", async () => {
    renderRunPage();
    click(await screen.findByRole("button", { name: "Show diff" }));
    expect(await screen.findByText("+lr = 0.01")).toBeVisible();
    expect(mockedApi.experimentsDiff).toHaveBeenCalledWith("test", "my-app", "v-prev", RUN);
    expect(clicks).toBeLessThanOrEqual(1);
  });

  it("F4: two clicks from a metric value to a copied restore command", async () => {
    renderRunPage();
    expect(await screen.findByTestId("metric-value-loss")).toBeVisible();
    click(screen.getByRole("button", { name: /Reproduce/ }));
    click(screen.getByRole("menuitem", { name: /vmn-exp restore/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(vmnExpCommand(["restore", "my/app", "-v", RUN])));
    expect(clicks).toBeLessThanOrEqual(2);
  });

  it("F6: a failed run opens on its output tail, before anything else", async () => {
    mockedApi.experiment.mockResolvedValue(fullDetail({
      status: runStatus({ status: "failed", exit_code: 1, error_summary: "boom" }),
      output_tail: { lines: ["epoch 38", "CUDA out of memory"], truncated: false },
    }));
    renderRunPage();
    const tail = await waitFor(() => {
      const pre = document.querySelector("pre.run-error-tail") as HTMLElement;
      expect(pre).not.toBeNull();
      return pre;
    });
    expect(tail).toBeVisible();
    expect(tail.textContent).toContain("CUDA out of memory");
    expect(sectionHeadings()[0]).toBe("Error");
    expect(clicks).toBe(0);
  });
});
