import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Mock the API module before any imports that use it
vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

// Mock ParamPlots to keep chart rendering out of these table tests
vi.mock("../../components/ParamPlots", () => ({
  default: () => <div data-testid="param-plots" />,
}));

// Mock NewExperiment to keep tests focused
vi.mock("../../components/NewExperiment", () => ({
  default: () => null,
}));

import { api } from "../../api";
import type { ExperimentRow, MetricsSchema } from "../../types";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

function makeRows(n: number): ExperimentRow[] {
  return Array.from({ length: n }, (_, i) => ({
    idx: i + 1,
    verstr: `0.0.${i + 1}-rc.1`,
    code_verstr: `0.0.${i + 1}`,
    timestamp: new Date(Date.now() - i * 60_000).toISOString(),
    note: i === 0 ? "first" : null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    metrics: { loss: 1.0 - i * 0.001, acc: 0.8 + i * 0.001 },
  }));
}

function renderLeaderboard() {
  return render(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Leaderboard virtualization", () => {
  it("renders a scrollable container with maxHeight and overflow", async () => {
    const schema: MetricsSchema = {
      loss: { goal: "min" },
      acc: { goal: "max", primary: true },
    };
    mockedApi.experiments.mockResolvedValue(makeRows(50));
    mockedApi.metricsSchema.mockResolvedValue(schema);

    renderLeaderboard();

    // Text is split across elements ("50" + " runs"), use a regex
    await waitFor(() => {
      expect(screen.getByText(/50\s*runs/)).toBeInTheDocument();
    });

    const scrollContainer = document.querySelector(".tbl-scroll") as HTMLElement;
    expect(scrollContainer).not.toBeNull();
    expect(scrollContainer.style.maxHeight).toBe("calc(100vh - 340px)");
    expect(scrollContainer.style.overflow).toBe("auto");
  });

  it("sets up virtualized tbody with relative positioning and height", async () => {
    mockedApi.experiments.mockResolvedValue(makeRows(100));
    mockedApi.metricsSchema.mockResolvedValue({});

    renderLeaderboard();

    await waitFor(() => {
      expect(screen.getByText(/100\s*runs/)).toBeInTheDocument();
    });

    const tbody = document.querySelector("tbody") as HTMLElement;
    expect(tbody).not.toBeNull();
    // Virtualized tbody has a height from getTotalSize() = 100 * 48 = 4800
    expect(tbody.style.position).toBe("relative");
    expect(parseInt(tbody.style.height, 10)).toBe(4800);

    // In jsdom the scroll container has 0 height so the virtualizer renders
    // zero visible rows. We verify the structure is correct (tbody height +
    // relative positioning) which proves the virtualizer is wired up.
    // In a real browser the rows would appear as absolutely-positioned <tr>s.
  });

  it("renders zero rows when experiment list is empty", async () => {
    mockedApi.experiments.mockResolvedValue([]);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderLeaderboard();

    await waitFor(() => {
      expect(screen.getByText(/No experiments yet/)).toBeInTheDocument();
    });
  });

  it("keeps the table header columns intact", async () => {
    const schema: MetricsSchema = {
      loss: { goal: "min" },
    };
    mockedApi.experiments.mockResolvedValue(makeRows(5));
    mockedApi.metricsSchema.mockResolvedValue(schema);

    renderLeaderboard();

    await waitFor(() => {
      expect(screen.getByText(/5\s*runs/)).toBeInTheDocument();
    });

    // Verify thead columns are still rendered correctly
    expect(screen.getByText("experiment")).toBeInTheDocument();
    expect(screen.getByText("note")).toBeInTheDocument();
    expect(screen.getByText("when")).toBeInTheDocument();
    expect(screen.getByText("#")).toBeInTheDocument();
  });
});
