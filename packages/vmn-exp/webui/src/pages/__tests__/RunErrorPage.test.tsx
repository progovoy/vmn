import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: (_ws: string, _app: string, v: string, f: string) => `/a/${v}/${f}`,
}));
vi.mock("../../components/TrainingCurves", () => ({
  default: () => <div data-testid="training-curves" />,
}));

import { api } from "../../api";
import type { ExperimentDetail, RunState, RunStatus } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

function status(state: RunState, extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: state, exit_code: null, started_at: null, finished_at: null, heartbeat: null,
    duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
    children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null, ...extra,
  };
}

function makeDetail(st: RunStatus, extra: Partial<ExperimentDetail> = {}): ExperimentDetail {
  return {
    metadata: { verstr: "0.0.2-rc.1", branch: "main", timestamp: "2026-01-01T12:00:00Z" },
    metrics: {}, series: {}, log: [], patches: {}, status: st, ...extra,
  };
}

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.2-rc.1"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

const card = () => document.querySelector(".run-error-card") as HTMLElement | null;

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("boom"))));
});
afterEach(() => vi.unstubAllGlobals());

describe("Run page error card", () => {
  it("shows the exception above the training curves", async () => {
    mockedApi.experiment.mockResolvedValue(makeDetail(status("failed", {
      exit_code: 1, error_summary: "RuntimeError: boom",
      error: { type: "RuntimeError", message: "boom", traceback: "Traceback\nRuntimeError: boom" },
    })));
    renderRun();
    const curves = await screen.findByTestId("training-curves");
    expect(card()).not.toBeNull();
    expect(card()!.querySelector(".run-error-headline")?.textContent).toBe("RuntimeError: boom");
    expect(card()!.compareDocumentPosition(curves) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("links a failed run without an exception to its output card", async () => {
    mockedApi.experiment.mockResolvedValue(makeDetail(status("failed", { exit_code: 3 }), {
      artifacts: [{ name: "outputs/output.log", size: 4 }],
    }));
    renderRun();
    await screen.findByTestId("training-curves");
    expect(card()!.textContent).toContain("No exception was recorded — exit code 3");
    expect(card()!.querySelector('a[href="#run-output"]')).not.toBeNull();
    expect(document.getElementById("run-output")).not.toBeNull();
  });

  it("shows no card for a stuck run", async () => {
    mockedApi.experiment.mockResolvedValue(makeDetail(status("stuck", { stale_sec: 600 })));
    renderRun();
    await screen.findByTestId("training-curves");
    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    expect(card()).toBeNull();
  });
});
