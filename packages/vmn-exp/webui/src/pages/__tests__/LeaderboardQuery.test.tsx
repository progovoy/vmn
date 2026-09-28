import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiments: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

vi.mock("../../components/ParamPlots", () => ({
  default: () => <div data-testid="param-plots" />,
}));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));

// jsdom gives the scroll container zero height, so the real virtualizer would
// render no rows. Render them all instead — this suite is about the query box.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48,
      })),
  }),
}));

import { api } from "../../api";
import type { ExperimentRow } from "../../types";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

function row(idx: number, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx,
    verstr: `0.0.${idx}`,
    code_verstr: `0.0.${idx}`,
    timestamp: "2026-01-01T12:00:00Z",
    note: null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    metrics: { loss: 0.5 },
    status: "succeeded",
    exit_code: 0,
    started_at: null,
    finished_at: null,
    heartbeat: null,
    duration_sec: null,
    pid: null,
    host: null,
    command: null,
    stale_sec: null,
    parent: null,
    children: [],
    kind: "single",
    depth: 0,
    tree_status: null,
    last_metric_at: null,
    ...extra,
  };
}

function renderLeaderboard() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const queryBox = () => screen.getByPlaceholderText(/metrics\./i);

/** A 400 from the list endpoint: the compiler's message, offset included. */
const queryError = (message: string) =>
  Object.assign(new Error(message), { status: 400 });

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Leaderboard query box", () => {
  it("shows a real example so the syntax is discoverable", async () => {
    mockedApi.experiments.mockResolvedValue([row(1)]);
    renderLeaderboard();

    await waitFor(() => expect(queryBox()).toBeInTheDocument());
    expect(queryBox().getAttribute("placeholder")).toMatch(/metrics\.loss < 0\.5/);
  });

  it("debounces typing into one request", async () => {
    vi.useFakeTimers();
    mockedApi.experiments.mockResolvedValue([row(1)]);

    renderLeaderboard();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);

    fireEvent.change(queryBox(), { target: { value: "metrics.loss <" } });
    fireEvent.change(queryBox(), { target: { value: "metrics.loss < 0.5" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(mockedApi.experiments).toHaveBeenCalledTimes(1);  // still waiting

    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(mockedApi.experiments).toHaveBeenCalledTimes(2);
    expect(mockedApi.experiments).toHaveBeenLastCalledWith(
      "test", "my-app", "timestamp", undefined, "metrics.loss < 0.5"
    );
  });

  it("sends the query alongside the picked statuses", async () => {
    mockedApi.experiments.mockResolvedValue([row(1)]);
    renderLeaderboard();

    await waitFor(() => expect(queryBox()).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    fireEvent.change(queryBox(), { target: { value: 'params.model = "xgb"' } });

    await waitFor(() =>
      expect(mockedApi.experiments).toHaveBeenLastCalledWith(
        "test", "my-app", "timestamp", "succeeded", 'params.model = "xgb"'
      )
    );
  });

  it("shows a 400's message inline and keeps the rows on screen", async () => {
    mockedApi.experiments.mockResolvedValue([row(1), row(2)]);
    renderLeaderboard();

    await waitFor(() => expect(screen.getByText("0.0.1")).toBeInTheDocument());

    mockedApi.experiments.mockRejectedValue(
      queryError("expected a value, found 'None' at offset 14")
    );
    fireEvent.change(queryBox(), { target: { value: "metrics.loss <" } });

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("at offset 14")
    );
    // The rows the user was looking at survive their own typo.
    expect(screen.getByText("0.0.1")).toBeInTheDocument();
    expect(screen.getByText("0.0.2")).toBeInTheDocument();
  });

  it("clears the error once the query parses", async () => {
    mockedApi.experiments.mockResolvedValue([row(1), row(2)]);
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("0.0.1")).toBeInTheDocument());

    mockedApi.experiments.mockRejectedValue(queryError("bad at offset 3"));
    fireEvent.change(queryBox(), { target: { value: "bad" } });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    mockedApi.experiments.mockResolvedValue([row(2)]);
    fireEvent.change(queryBox(), { target: { value: "metrics.loss < 0.5" } });

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByText("0.0.1")).toBeNull();
  });

  it("stays usable when a query matches nothing", async () => {
    mockedApi.experiments.mockResolvedValue([row(1)]);
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("0.0.1")).toBeInTheDocument());

    mockedApi.experiments.mockResolvedValue([]);
    fireEvent.change(queryBox(), { target: { value: "metrics.loss < 0" } });

    // No rows, but the box that filtered them away is still there to undo.
    await waitFor(() => expect(screen.queryByText("0.0.1")).toBeNull());
    expect(queryBox()).toBeInTheDocument();
  });

  it("still reports a non-query failure as a page error", async () => {
    mockedApi.experiments.mockRejectedValue(new Error("boom"));
    renderLeaderboard();

    await waitFor(() =>
      expect(document.querySelector(".error")?.textContent).toContain("boom")
    );
  });
});
