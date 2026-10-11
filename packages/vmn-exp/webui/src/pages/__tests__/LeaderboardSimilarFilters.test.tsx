import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiments: vi.fn(), experimentsPaged: vi.fn(), metricsSchema: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));
vi.mock("../../components/ParamPlots", () => ({ default: () => <div /> }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 48, size: 48 })),
  }),
}));

import { api } from "../../api";
import { textSimilar } from "../../apiSimilar";
import type { ExperimentRow } from "../../types";
import Leaderboard from "../Leaderboard";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mockedText = textSimilar as unknown as ReturnType<typeof vi.fn>;

const ROW = {
  idx: 1, verstr: "0.0.1", code_verstr: "0.0.1", timestamp: "2026-01-01T12:00:00Z",
  note: null, branch: "main", base_version: "0.0.1", metrics: { loss: 0.5 },
  status: "succeeded", children: [], kind: "single", depth: 0,
} as unknown as ExperimentRow;

const FILTERED = "/ws/test/app/my-app?status=failed,succeeded&branch=main&archived=1"
  + `&search=batch&q=${encodeURIComponent("metrics.loss < 0.5")}`;

function renderBoard(url: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const toggle = () => screen.getByRole("button", { name: /^similar$/i });
const box = () => screen.getByRole("textbox", { name: /search runs/i });

/** The options of the last similar-runs request for *text*. */
function lastOptions(text: string) {
  const calls = mockedText.mock.calls.filter((call) => call[2] === text);
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][3];
}

async function similarMode(url: string, text = "focal loss") {
  renderBoard(url);
  expect(await screen.findByText("0.0.1")).toBeInTheDocument();
  fireEvent.click(toggle());
  fireEvent.change(box(), { target: { value: text } });
  await waitFor(() => expect(mockedText).toHaveBeenCalled());
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experiments.mockResolvedValue([ROW]);
  // Archived rows come through the paged list.
  mockedApi.experimentsPaged.mockResolvedValue({ rows: [ROW], total: 1 });
  mockedText.mockResolvedValue({ items: [], truncated: false });
});

describe("Leaderboard similar mode filters", () => {
  it("narrows the similar runs by the bar's query, branch, statuses and archived toggle", async () => {
    await similarMode(FILTERED);
    const opts = lastOptions("focal loss");
    expect(opts.archived).toBe(true);
    expect(opts.query).toContain("metrics.loss < 0.5");
    expect(opts.query).toContain('branch = "main"');
    expect(opts.query).toContain('status in ("failed", "succeeded")');
    // The table's search text is not the similar text: it is left out.
    expect(opts.query).not.toContain("batch");
  });

  it("asks again when a status is toggled in the mode", async () => {
    await similarMode("/ws/test/app/my-app");
    expect(lastOptions("focal loss").query).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    await waitFor(() => expect(lastOptions("focal loss").query).toBe('status in ("failed")'));
  });
});
