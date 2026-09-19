import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Polyfill ResizeObserver for jsdom (recharts needs it)
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

// Mock the API module before any imports that use it
vi.mock("../../api", () => ({
  api: {
    experiment: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { api } from "../../api";
import type { ExperimentDetail } from "../../types";
import Overlay from "../Overlay";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
};

function makeDetail(verstr: string, series: Record<string, { step: number; value: number }[]>): ExperimentDetail {
  return {
    metadata: { verstr, branch: "main", base_version: "0.0.1" },
    metrics: {},
    series: Object.fromEntries(
      Object.entries(series).map(([k, pts]) =>
        [k, pts.map((p) => ({ step: p.step, value: p.value, ts: null }))]
      )
    ),
    log: [],
    patches: {},
  };
}

function renderOverlay(runs: string[]) {
  const search = runs.length ? `?runs=${runs.join(",")}` : "";
  return render(
    <MemoryRouter initialEntries={[`/ws/test/app/my-app/overlay${search}`]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/overlay" element={<Overlay />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Overlay page", () => {
  it("renders a chart per shared metric across selected runs", async () => {
    const d1 = makeDetail("0.0.1-rc.1", {
      loss: [{ step: 0, value: 1.0 }, { step: 1, value: 0.8 }],
      acc: [{ step: 0, value: 0.5 }, { step: 1, value: 0.7 }],
    });
    const d2 = makeDetail("0.0.2-rc.1", {
      loss: [{ step: 0, value: 0.9 }, { step: 1, value: 0.6 }],
      acc: [{ step: 0, value: 0.6 }, { step: 1, value: 0.8 }],
    });
    mockedApi.experiment
      .mockResolvedValueOnce(d1)
      .mockResolvedValueOnce(d2);

    renderOverlay(["0.0.1-rc.1", "0.0.2-rc.1"]);

    await waitFor(() => {
      // Both shared metrics should have chart headings
      expect(screen.getByText("loss")).toBeInTheDocument();
      expect(screen.getByText("acc")).toBeInTheDocument();
    });
  });

  it("renders one line per run per metric", async () => {
    const d1 = makeDetail("0.0.1-rc.1", {
      loss: [{ step: 0, value: 1.0 }, { step: 1, value: 0.8 }],
    });
    const d2 = makeDetail("0.0.2-rc.1", {
      loss: [{ step: 0, value: 0.9 }, { step: 1, value: 0.6 }],
    });
    mockedApi.experiment
      .mockResolvedValueOnce(d1)
      .mockResolvedValueOnce(d2);

    renderOverlay(["0.0.1-rc.1", "0.0.2-rc.1"]);

    await waitFor(() => {
      expect(screen.getByText("loss")).toBeInTheDocument();
    });

    // Each run's verstr should appear in the legend
    expect(screen.getByText("0.0.1-rc.1")).toBeInTheDocument();
    expect(screen.getByText("0.0.2-rc.1")).toBeInTheDocument();
  });

  it("shows run legend with verstr labels", async () => {
    const d1 = makeDetail("0.0.1-rc.1", {
      loss: [{ step: 0, value: 1.0 }, { step: 1, value: 0.8 }],
    });
    const d2 = makeDetail("0.0.3-rc.2", {
      loss: [{ step: 0, value: 0.5 }, { step: 1, value: 0.4 }],
    });
    mockedApi.experiment
      .mockResolvedValueOnce(d1)
      .mockResolvedValueOnce(d2);

    renderOverlay(["0.0.1-rc.1", "0.0.3-rc.2"]);

    await waitFor(() => {
      expect(screen.getByText("0.0.1-rc.1")).toBeInTheDocument();
      expect(screen.getByText("0.0.3-rc.2")).toBeInTheDocument();
    });
  });

  it("shows a message when no runs are selected", async () => {
    renderOverlay([]);

    await waitFor(() => {
      expect(screen.getByText(/no runs selected/i)).toBeInTheDocument();
    });
  });
});
