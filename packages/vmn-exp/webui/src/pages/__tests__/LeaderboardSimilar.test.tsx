import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiments: vi.fn(), metricsSchema: vi.fn() },
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

const HIT = {
  workspace: "test", app: "my/app", verstr: "0.0.7-dev.focal", name: "focal", score: 1,
  reasons: ["shared: focal loss"], signals: { text: 1 }, group_size: 1, goal: null,
  author: "bob@x.io", timestamp: null, status: "succeeded", note: null, intent: null,
};

function renderBoard() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/test/app/my-app"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

const toggle = () => screen.getByRole("button", { name: /^similar$/i });
const box = () => screen.getByRole("textbox", { name: /search runs/i });

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experiments.mockResolvedValue([ROW]);
  mockedText.mockResolvedValue({ items: [HIT], truncated: false });
});

describe("Leaderboard similar mode", () => {
  it("replaces the table with the runs similar to the typed text", async () => {
    renderBoard();
    expect(await screen.findByText("0.0.1")).toBeInTheDocument();
    fireEvent.click(toggle());
    fireEvent.change(box(), { target: { value: "focal loss" } });
    expect(await screen.findByRole("link", { name: "focal" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.7-dev.focal",
    );
    expect(mockedText).toHaveBeenCalledWith("test", "my-app", "focal loss", { allApps: false });
    expect(screen.queryByText("0.0.1")).toBeNull();
    expect(screen.getByText("shared: focal loss")).toBeInTheDocument();
  });

  it("asks for a text before searching", async () => {
    renderBoard();
    expect(await screen.findByText("0.0.1")).toBeInTheDocument();
    fireEvent.click(toggle());
    expect(await screen.findByText(/describe a run/i)).toBeInTheDocument();
    expect(mockedText).not.toHaveBeenCalled();
  });

  it("restores the table when the mode is left", async () => {
    renderBoard();
    expect(await screen.findByText("0.0.1")).toBeInTheDocument();
    fireEvent.click(toggle());
    fireEvent.change(box(), { target: { value: "focal loss" } });
    expect(await screen.findByRole("link", { name: "focal" })).toBeInTheDocument();
    fireEvent.click(toggle());
    expect(await screen.findByText("0.0.1")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "focal" })).toBeNull();
  });

  it("shows the server's complaint about the text", async () => {
    mockedText.mockRejectedValue(Object.assign(new Error("text is over 4096 bytes"), { status: 400 }));
    renderBoard();
    expect(await screen.findByText("0.0.1")).toBeInTheDocument();
    fireEvent.click(toggle());
    fireEvent.change(box(), { target: { value: "x" } });
    await waitFor(() => expect(screen.getByText(/over 4096 bytes/)).toBeInTheDocument());
  });
});
