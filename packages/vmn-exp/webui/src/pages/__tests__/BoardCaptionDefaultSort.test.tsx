/** The caption names the order the server was asked for: with no sort in
 *  the URL the board is newest first, not by the app's primary metric. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/ParallelCoordinates", () => ({ default: () => null }));
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
import Leaderboard from "../Experiments/AllRunsView";

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
    params: {},
    metrics: {},
    status: "succeeded",
    ...extra,
  };
}

const page = (rows: ExperimentRow[]) => Object.assign([...rows], { total: rows.length });
const sortText = () => document.querySelector(".board-caption-sort")?.textContent;

function renderAt(url: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({ value: { goal: "max", primary: true } });
});

describe("the board's caption matches its order", () => {
  it("says newest first when no sort is chosen, even with a primary metric", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(2, { status: "created" }), row(1, { metrics: { value: 3 } })]));
    renderAt("/ws/test/app/my-app");
    await screen.findByText("0.0.2-dev.x");
    await waitFor(() => expect(mockedApi.metricsSchema).toHaveBeenCalled());
    expect(mockedApi.experiments).toHaveBeenLastCalledWith("test", "my-app", "idx", undefined);
    await waitFor(() => expect(sortText()).toBe("newest first"));
    expect(document.body).not.toHaveTextContent(/sorted by value/);
  });

  it("names the metric once the URL sorts by it", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1, { metrics: { value: 3 } })]));
    renderAt("/ws/test/app/my-app?sort=value");
    await screen.findByText("0.0.1-dev.x");
    expect(mockedApi.experiments).toHaveBeenLastCalledWith("test", "my-app", "value", undefined);
    await waitFor(() => expect(sortText()).toBe("sorted by value, best first"));
  });
});
