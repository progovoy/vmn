import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";
import { currentSignal } from "../../requestScope";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
// A stand-in create form: one button that reports success.
vi.mock("../../components/NewExperiment", () => ({
  default: ({ onCreated }: { onCreated: () => void }) => (
    <button onClick={onCreated}>fake-create</button>
  ),
}));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import type { ExperimentRow } from "../../types";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  experimentsPaged: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

type Rows = ExperimentRow[] & { total?: number };

function row(i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx: i,
    verstr: `0.0.${i}-dev.x`,
    code_verstr: `0.0.${i}`,
    timestamp: new Date(Date.now() - i * 60_000).toISOString(),
    note: null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    params: {},
    metrics: {},
    status: "succeeded",
    ...extra,
  };
}

const page = (rows: ExperimentRow[], total?: number): Rows =>
  Object.assign([...rows], { total: total ?? rows.length });

function renderLeaderboard(path = "/ws/test/app/my-app") {
  return renderWithClient(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("Leaderboard paging", () => {
  it("shows the server total, not just the loaded page", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1), row(2)], 5000));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText(/2 of 5000 runs/)).toBeInTheDocument());
  });

  it("loads the next page with the same filters", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1), row(2)], 3));
    mockedApi.experimentsPaged.mockResolvedValue({ rows: [row(3)], total: 3 });
    renderLeaderboard();
    await waitFor(() => screen.getByRole("button", { name: /load more/i }));
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(screen.getByText("0.0.3-dev.x")).toBeInTheDocument());
    expect(mockedApi.experimentsPaged).toHaveBeenCalledWith(
      "test", "my-app",
      expect.objectContaining({ offset: 2, limit: 200 }),
    );
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });
});

describe("Leaderboard request ordering", () => {
  it("never lets an older response overwrite a newer one", async () => {
    const resolvers: ((rows: Rows) => void)[] = [];
    mockedApi.experiments.mockImplementation(
      () => new Promise<Rows>((r) => resolvers.push(r))
    );
    renderLeaderboard();
    await waitFor(() => expect(resolvers.length).toBe(1));

    // A status filter change fires a second, newer request.
    await act(async () => { resolvers[0](page([row(1, { status: "running" })])); });
    await waitFor(() => screen.getByRole("button", { name: "running" }));
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    await waitFor(() => expect(resolvers.length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    await waitFor(() => expect(resolvers.length).toBe(3));

    // Newest answers first, then the stale one arrives late.
    await act(async () => { resolvers[2](page([row(7, { verstr: "newest" })])); });
    await act(async () => { resolvers[1](page([row(8, { verstr: "stale" })])); });
    await waitFor(() => expect(screen.getByText("newest")).toBeInTheDocument());
    expect(screen.queryByText("stale")).toBeNull();
  });

  it("aborts the in-flight request when the filter changes", async () => {
    const signals: (AbortSignal | undefined)[] = [];
    mockedApi.experiments.mockImplementation(() => {
      signals.push(currentSignal());
      // The first load answers; every later request stays in flight.
      return signals.length === 1
        ? Promise.resolve(page([row(1, { status: "running" })]))
        : new Promise<Rows>(() => {});
    });
    renderLeaderboard();
    await waitFor(() => screen.getByRole("button", { name: "failed" }));
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    await waitFor(() => expect(signals.length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    await waitFor(() => expect(signals.length).toBe(3));
    expect(signals[1]).toBeDefined();
    expect(signals[1]!.aborted).toBe(true);
    expect(signals[2]!.aborted).toBe(false);
  });
});

describe("Leaderboard params", () => {
  it("builds param columns from row.params, strings included", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { params: { model: "resnet50", lr: 0.1 } }),
    ]));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("resnet50")).toBeInTheDocument());
    const head = document.querySelector("thead") as HTMLElement;
    expect(within(head).getByText("model")).toBeInTheDocument();
  });

  it("keeps a hidden param column hidden across polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { status: "running", params: { model: "alpha-model", seed: 1 } }),
    ]));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("alpha-model")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Columns"));
    fireEvent.click(screen.getByRole("checkbox", { name: "model" }));
    expect(screen.queryByText("alpha-model")).toBeNull();

    // A poll returns a fresh (equal) set of param names.
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { status: "running", params: { model: "beta-model", seed: 1 } }),
    ]));
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    await waitFor(() => expect(mockedApi.experiments.mock.calls.length).toBeGreaterThan(1));
    expect(screen.queryByText("beta-model")).toBeNull();
    vi.useRealTimers();
  });
});

describe("Leaderboard metrics", () => {
  it("renders a null (non-finite) metric as a dash and never as best", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: null as unknown as number } }),
      row(2, { metrics: { loss: 0.5 } }),
      row(3, { metrics: { loss: 0.7 } }),
    ]));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("0.5")).toBeInTheDocument());
    expect(screen.getByText("0.5").className).toContain("best");
    const first = screen.getByText("0.0.1-dev.x").closest("tr") as HTMLElement;
    expect(within(first).getByText("–")).toBeInTheDocument();
  });
});

describe("Leaderboard create refetch", () => {
  it("refetches with the active status and query filters", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1, { status: "running" })]));
    renderLeaderboard("/ws/test/app/my-app?new=1");
    await waitFor(() => screen.getByRole("button", { name: "running" }));
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    await waitFor(() =>
      expect(mockedApi.experiments).toHaveBeenLastCalledWith(
        "test", "my-app", "timestamp", "running"
      )
    );
    fireEvent.click(screen.getByText("fake-create"));
    await waitFor(() => expect(mockedApi.experiments.mock.calls.length).toBeGreaterThan(2));
    const calls = mockedApi.experiments.mock.calls;
    const last = calls[calls.length - 1];
    expect(last[3]).toBe("running");
  });
});

describe("Leaderboard column alignment", () => {
  it("gives every body cell the same fixed width as its header cell", async () => {
    mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3 }, params: { model: "x" } }),
      row(2, { metrics: { loss: 0.4 }, params: { model: "y" } }),
    ]));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("0.3")).toBeInTheDocument());

    const table = document.querySelector(".tbl-scroll table") as HTMLElement;
    expect(table.style.tableLayout).toBe("fixed");
    const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
    const widths = heads.map((h) => h.style.width);
    expect(widths.every((w) => /px$/.test(w))).toBe(true);
    const bodyRows = [...document.querySelectorAll("tbody tr.row")] as HTMLElement[];
    expect(bodyRows.length).toBe(2);
    bodyRows.forEach((tr) => {
      const cells = [...tr.querySelectorAll("td")] as HTMLElement[];
      expect(cells.map((c) => c.style.width)).toEqual(widths);
      expect(tr.style.tableLayout).toBe("fixed");
    });
  });
});
