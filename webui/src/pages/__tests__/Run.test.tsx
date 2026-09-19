import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { api } from "../../api";
import type { ExperimentDetail } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as {
  experiment: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

/** Builds a detail with series data for testing chart modes. */
function makeDetail(opts?: {
  withTimestamps?: boolean;
  partialTimestamps?: boolean;
}): ExperimentDetail {
  const withTs = opts?.withTimestamps ?? true;
  const partial = opts?.partialTimestamps ?? false;

  const points = Array.from({ length: 5 }, (_, i) => ({
    step: i * 10,
    value: 1.0 - i * 0.1,
    ts: withTs
      ? new Date(Date.UTC(2026, 0, 1, 12, 0, i * 30)).toISOString()
      : null,
  }));

  if (partial && points.length > 0) {
    points[2].ts = null;
  }

  return {
    metadata: {
      verstr: "0.0.1-rc.1",
      branch: "main",
      base_version: "0.0.1",
      base_commit: "abc1234567890",
      timestamp: "2026-01-01T12:00:00Z",
      note: "",
    },
    metrics: { loss: 0.5, acc: 0.95 },
    series: { loss: points },
    log: [
      { timestamp: "2026-01-01T12:00:00Z", type: "create" },
    ],
    patches: {},
  };
}

function renderRun() {
  return render(
    <MemoryRouter initialEntries={["/ws/test/app/my-app/run/0.0.1-rc.1"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Run writer provenance badge", () => {
  it("shows _writer badge when log entry has _writer field", async () => {
    const detail = makeDetail();
    detail.log = [
      { timestamp: "2026-01-01T12:00:00Z", type: "create", _writer: "gpu0" },
    ];
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("gpu0")).toBeInTheDocument();
    });
    expect(screen.getByText("gpu0").className).toContain("badge");
  });

  it("does not show badge when log entry has no _writer field", async () => {
    const detail = makeDetail();
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("log")).toBeInTheDocument();
    });
    const timeline = document.querySelector(".timeline");
    expect(timeline?.querySelector(".badge")).toBeNull();
  });
});

describe("Run provenance metadata", () => {
  it("shows from_snapshot when present in metadata", async () => {
    const detail = makeDetail();
    detail.metadata.from_snapshot = "0.0.1-snap.3";
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("from snapshot")).toBeInTheDocument();
    });
    expect(screen.getByText("0.0.1-snap.3")).toBeInTheDocument();
  });

  it("shows code_verstr when it differs from verstr", async () => {
    const detail = makeDetail();
    detail.metadata.code_verstr = "0.0.2";
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("code version")).toBeInTheDocument();
    });
    expect(screen.getByText("0.0.2")).toBeInTheDocument();
  });

  it("does NOT show code_verstr when it matches verstr", async () => {
    const detail = makeDetail();
    detail.metadata.code_verstr = "0.0.1-rc.1";
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("metadata")).toBeInTheDocument();
    });
    expect(screen.queryByText("code version")).not.toBeInTheDocument();
  });
});

describe("Run x-axis mode", () => {
  it("defaults to step mode using step values as X", async () => {
    const detail = makeDetail({ withTimestamps: true });
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("training curves")).toBeInTheDocument();
    });

    // Step button should be active (have primary class)
    const stepBtn = screen.getByRole("button", { name: "Step" });
    expect(stepBtn.className).toContain("primary");
  });

  it("computes relative time as seconds from first timestamp", async () => {
    // Points have timestamps 30s apart: 12:00:00, 12:00:30, 12:01:00, ...
    const detail = makeDetail({ withTimestamps: true });
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("training curves")).toBeInTheDocument();
    });

    const relBtn = screen.getByRole("button", { name: "Relative" });
    fireEvent.click(relBtn);

    // Relative button should now be active
    expect(relBtn.className).toContain("primary");

    // Step button should no longer be active
    const stepBtn = screen.getByRole("button", { name: "Step" });
    expect(stepBtn.className).not.toContain("primary");
  });

  it("disables wall and relative buttons when ts is null in any point", async () => {
    const detail = makeDetail({ withTimestamps: false });
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("training curves")).toBeInTheDocument();
    });

    const wallBtn = screen.getByRole("button", { name: "Wall" });
    const relBtn = screen.getByRole("button", { name: "Relative" });

    expect(wallBtn).toBeDisabled();
    expect(relBtn).toBeDisabled();

    // Step should still be enabled
    const stepBtn = screen.getByRole("button", { name: "Step" });
    expect(stepBtn).not.toBeDisabled();
  });

  it("disables wall and relative when timestamps are partial", async () => {
    const detail = makeDetail({ partialTimestamps: true });
    mockedApi.experiment.mockResolvedValue(detail);
    mockedApi.metricsSchema.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByText("training curves")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: "Wall" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Relative" })).toBeDisabled();
  });
});
