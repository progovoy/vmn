import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), action: vi.fn(), job: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../components/TrainingCurves", () => ({ default: () => null }));

import { api } from "../../api";
import { FakeSource, lastSource } from "../../hooks/__tests__/fakeEventSource";
import { createQueryClient } from "../../queryClient";
import type { ExperimentDetail } from "../../types";
import Run from "../Run";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const VERSTR = "0.0.2-rc.1";
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

const running: ExperimentDetail["status"] = {
  status: "running", exit_code: null, started_at: null, finished_at: null, heartbeat: null,
  duration_sec: null, pid: null, host: null, command: null, stale_sec: null, parent: null,
  children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null,
};

const detail = (): ExperimentDetail => ({
  metadata: { verstr: VERSTR, branch: "main", base_version: "0.0.1", timestamp: "2026-01-01T12:00:00Z" },
  metrics: {}, series: {}, log: [], patches: {}, status: running,
});

function renderRun(ref = VERSTR) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${ref}`]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.experiment.mockImplementation(async () => detail());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the run page follows its subtree's live events (plan 23 S5)", () => {
  it("opens a stream scoped to the run's verstr (a ref resolved) and stops polling", async () => {
    renderRun("latest");
    await tick(0);
    expect(lastSource().url).toBe(`/api/v1/workspaces/test/apps/my-app/events?scope=${VERSTR}`);
    act(() => lastSource().open());
    await tick(60_000);
    expect(m.experiment).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/live · updated \S+ ago/)).toBeInTheDocument();
  });

  it("refetches the detail on a change event", async () => {
    renderRun();
    await tick(0);
    act(() => lastSource().open());
    act(() => lastSource().emit("change", { generation: "2.0", changed: { rows: 1 } }));
    await tick(0);
    expect(m.experiment).toHaveBeenCalledTimes(2);
  });

  it("polls as before once the server refuses the stream", async () => {
    renderRun();
    await tick(0);
    act(() => lastSource().fail(true));
    await tick(15_000);
    expect(m.experiment).toHaveBeenCalledTimes(2);
  });

  it("closes the stream while paused", async () => {
    renderRun();
    await tick(0);
    act(() => lastSource().open());
    act(() => screen.getByRole("button", { name: "Pause" }).click());
    expect(lastSource().closed).toBe(true);
  });
});
