import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), action: vi.fn(), job: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
// Records the series each render hands the chart, to check poll identity.
const seriesSeen: unknown[] = [];
vi.mock("../../components/TrainingCurves", () => ({
  default: ({ series }: { series: unknown }) => { seriesSeen.push(series); return null; },
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import { rowsKey } from "../../queries";
import type { ExperimentDetail, ExperimentRow } from "../../types";
import Run from "../Run";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const VERSTR = "0.0.2-rc.1";

function detail(extra: Partial<ExperimentDetail> = {}): ExperimentDetail {
  return {
    metadata: {
      verstr: VERSTR, branch: "main", base_version: "0.0.1",
      base_commit: "abc1234567890", timestamp: "2026-01-01T12:00:00Z", note: "from detail",
    },
    metrics: { loss: 0.5 },
    series: { loss: [{ step: 1, value: 0.5, ts: null }] },
    log: [{ timestamp: "2026-01-01T12:00:00Z", type: "run", duration_sec: 3700 }],
    patches: {},
    ...extra,
  };
}

const cachedRow: ExperimentRow = {
  idx: 2, verstr: VERSTR, code_verstr: VERSTR, timestamp: "2026-01-01T12:00:00Z",
  note: "row note", branch: "feat/row", base_version: "0.0.1", user_meta: null,
  params: { model: "resnet" }, metrics: { acc: 0.93 }, status: "running",
  duration_sec: 125, children: [],
};

function renderRun(client: QueryClient = createQueryClient()) {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${VERSTR}`]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  vi.clearAllMocks();
  seriesSeen.length = 0;
  m.metricsSchema.mockResolvedValue({});
});
afterEach(() => { vi.useRealTimers(); });

describe("Run first paint", () => {
  it("paints header, status, metrics and params from the cached row while the detail loads", () => {
    m.experiment.mockImplementation(() => new Promise(() => {}));
    const client = createQueryClient();
    client.setQueryData(rowsKey("test", "my-app", {}), { rows: [cachedRow], total: 1 });
    renderRun(client);

    expect(screen.getByRole("heading", { name: VERSTR })).toBeInTheDocument();
    expect(screen.getByText("row note")).toBeInTheDocument();
    expect(screen.getByText("feat/row")).toBeInTheDocument();
    expect(document.querySelector(".status-pill.running")).not.toBeNull();
    expect(screen.getByText("acc")).toBeInTheDocument();
    expect(screen.getByText("0.93")).toBeInTheDocument();
    expect(screen.getByText("resnet")).toBeInTheDocument();
  });
});

describe("Run formatting", () => {
  it("formats the status duration and the runtime on the duration ladder", async () => {
    m.experiment.mockResolvedValue(detail({
      status: {
        status: "succeeded", exit_code: 0, started_at: null, finished_at: null, heartbeat: null,
        duration_sec: 7300, pid: null, host: null, command: null, stale_sec: null, parent: null,
        children: [], kind: "single", depth: 0, tree_status: null, last_metric_at: null,
      },
    }));
    renderRun();
    expect(await screen.findByText("2h")).toBeInTheDocument();
    expect(screen.getByText("1h")).toBeInTheDocument();
  });

  it("labels the live toggle's off state", async () => {
    m.experiment.mockResolvedValue(detail());
    renderRun();
    expect(await screen.findByRole("button", { name: /live off/i })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("Run polling", () => {
  it("keeps unchanged parts of the detail identical across polls, so charts don't redraw", async () => {
    vi.useFakeTimers();
    m.experiment.mockImplementation(async () => detail());
    renderRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fireEvent.click(screen.getByRole("button", { name: /live off/i }));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(m.experiment).toHaveBeenCalledTimes(2);
    const seen = seriesSeen.filter(Boolean);
    expect(seen.length).toBeGreaterThan(1);
    expect(seen[seen.length - 1]).toBe(seen[0]);
  });
});

describe("Run note editor", () => {
  it("saves a note through exp_add and shows it at once", async () => {
    m.experiment.mockResolvedValue(detail());
    m.action.mockResolvedValue({ id: "j1", status: "running", command: [], exit_code: null, log: "", noop: false });
    m.job.mockResolvedValue({ id: "j1", status: "succeeded", command: [], exit_code: 0, log: "", noop: false });
    renderRun();
    fireEvent.click(await screen.findByRole("button", { name: /edit note/i }));
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "better lr" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));

    expect(screen.getByText("better lr")).toBeInTheDocument();
    expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_add", { verstr: VERSTR, note: "better lr" });
  });

  it("rolls the note back when the job fails", async () => {
    m.experiment.mockResolvedValue(detail());
    m.action.mockResolvedValue({ id: "j1", status: "running", command: [], exit_code: null, log: "", noop: false });
    m.job.mockResolvedValue({ id: "j1", status: "failed", command: [], exit_code: 1, log: "boom", noop: false });
    renderRun();
    fireEvent.click(await screen.findByRole("button", { name: /edit note/i }));
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "doomed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(screen.getByText("doomed")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("doomed")).toBeNull(), { timeout: 2000 });
    expect(screen.getByText("from detail")).toBeInTheDocument();
  });
});
