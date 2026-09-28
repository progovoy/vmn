import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

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
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
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
  mockedApi.metricsSchema.mockResolvedValue({ loss: { goal: "min" } });
});

describe("Leaderboard sticky header + pinned identifier column", () => {
  it("pins every header cell to the top of the scroll container with a solid background", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3 } }),
      row(2, { metrics: { loss: 0.4 } }),
    ]));
    renderLeaderboard();
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());

    const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
    expect(heads.length).toBeGreaterThan(0);
    heads.forEach((th) => {
      expect(th.style.position).toBe("sticky");
      expect(th.style.top).toBe("0px");
      expect(th.style.background).toBe("var(--surface-1)");
    });
  });

  it("pins the experiment (run identifier) header cell to the left, above the other headers", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.3 } })]));
    renderLeaderboard();
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());

    const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
    const expHead = heads.find((th) => th.textContent === "experiment") as HTMLElement;
    const idxHead = heads.find((th) => th.textContent === "#") as HTMLElement;
    expect(expHead).toBeTruthy();
    expect(expHead.style.position).toBe("sticky");
    // Left offset = the summed widths of the check/#/status columns before it.
    expect(expHead.style.left).toBe("200px");
    expect(Number(expHead.style.zIndex)).toBeGreaterThan(Number(idxHead.style.zIndex));
  });

  it("pins the run identifier body column to the left with a solid theme background", async () => {
    mockedApi.experiments.mockResolvedValue(page([row(1, { metrics: { loss: 0.3 } })]));
    renderLeaderboard();
    await waitFor(() => expect(screen.getByText("0.0.1-dev.x")).toBeInTheDocument());

    const cell = document.querySelector("tbody td.exp-cell") as HTMLElement;
    expect(cell).toBeTruthy();
    expect(cell.style.position).toBe("sticky");
    expect(cell.style.left).toBe("200px");
    expect(cell.style.background).toBe("var(--surface-1)");
    expect(Number(cell.style.zIndex)).toBeGreaterThan(0);
  });
});
