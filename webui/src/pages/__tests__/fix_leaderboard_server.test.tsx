import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

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
// A parallel view whose only control reports a brush over row index 1.
const parallelRows: number[] = [];
vi.mock("../../components/ParallelCoordinates", () => ({
  default: ({ rows, onBrush }: { rows: unknown[]; onBrush?: (i: number[] | null) => void }) => {
    parallelRows.push(rows.length);
    return <button onClick={() => onBrush?.([1])}>fake-brush</button>;
  },
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

const page = (rows: ExperimentRow[]) => Object.assign([...rows], { total: rows.length });

function renderLeaderboard() {
  return render(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const verstrsInTable = () =>
  screen.queryAllByText(/^0\.0\.\d-dev\.x$/).map((el) => el.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  parallelRows.length = 0;
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("sort direction is the server's job", () => {
  it("asks for best first, then worst first, and keeps the server's order", async () => {
    const rows = [row(1, { metrics: { loss: 0.9 } }), row(2, { metrics: { loss: 0.1 } })];
    mockedApi.experiments.mockResolvedValue(page(rows));
    mockedApi.experimentsPaged.mockResolvedValue({ rows, total: 2 });
    renderLeaderboard();
    const header = await screen.findByTitle(/sort by loss/);

    fireEvent.click(header);
    await waitFor(() =>
      expect(mockedApi.experimentsPaged).toHaveBeenLastCalledWith(
        "test", "my-app", expect.objectContaining({ sort: "loss", order: "asc" }),
      ),
    );
    fireEvent.click(header);
    await waitFor(() =>
      expect(mockedApi.experimentsPaged).toHaveBeenLastCalledWith(
        "test", "my-app", expect.objectContaining({ sort: "loss", order: "desc" }),
      ),
    );
    // Whatever the direction, the page is shown as the server ordered it.
    await waitFor(() => expect(verstrsInTable()).toEqual(["0.0.1-dev.x", "0.0.2-dev.x"]));
  });
});

describe("free-text search runs on the server", () => {
  it("sends the search box as a query over verstr, note and branch", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1)]));
    renderLeaderboard();
    fireEvent.change(await screen.findByPlaceholderText(/search/i), { target: { value: "bat" } });

    await waitFor(() =>
      expect(mockedApi.experiments).toHaveBeenLastCalledWith(
        "test", "my-app", undefined, undefined,
        'verstr ~ "bat" or note ~ "bat" or branch ~ "bat"',
      ),
    );
  });

  it("ANDs the search with a typed query and picks a quote the text lacks", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1)]));
    renderLeaderboard();
    fireEvent.change(await screen.findByLabelText("Filter query"), {
      target: { value: "metrics.loss < 0.5" },
    });
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'say "hi"' } });

    await waitFor(() =>
      expect(mockedApi.experiments).toHaveBeenLastCalledWith(
        "test", "my-app", undefined, undefined,
        "(metrics.loss < 0.5) and (verstr ~ 'say \"hi\"' or note ~ 'say \"hi\"' or branch ~ 'say \"hi\"')",
      ),
    );
  });
});

describe("brushing the parallel view", () => {
  it("filters the table to the brushed runs and keeps the chart's rows whole", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1), row(2), row(3)]));
    renderLeaderboard();
    fireEvent.click(await screen.findByRole("button", { name: "Parallel" }));
    fireEvent.click(await screen.findByRole("button", { name: "fake-brush" }));

    await waitFor(() => expect(verstrsInTable()).toEqual(["0.0.2-dev.x"]));
    expect(parallelRows[parallelRows.length - 1]).toBe(3);
  });
});
