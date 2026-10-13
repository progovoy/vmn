import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
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
import { FakeSource, lastSource } from "../../hooks/__tests__/fakeEventSource";
import { page, renderBoard, row } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1, { status: "running" })]));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the board follows the app's live events (plan 23 S5)", () => {
  it("opens the app's stream and, while it is open, does not poll", async () => {
    renderBoard();
    await tick(0);
    expect(lastSource().url).toBe("/api/v1/workspaces/test/apps/my-app/events");
    act(() => lastSource().open());
    const before = m.experiments.mock.calls.length;
    await tick(60_000);
    expect(m.experiments).toHaveBeenCalledTimes(before);
  });

  it("refreshes its rows on a change event", async () => {
    renderBoard();
    await tick(0);
    act(() => lastSource().open());
    const before = m.experiments.mock.calls.length;
    act(() => lastSource().emit("change", { generation: "2.0", changed: { rows: 1 } }));
    await tick(0);
    expect(m.experiments).toHaveBeenCalledTimes(before + 1);
  });

  it("polls as before once the server refuses the stream", async () => {
    renderBoard();
    await tick(0);
    act(() => lastSource().fail(true));
    const before = m.experiments.mock.calls.length;
    await tick(15_000);
    expect(m.experiments).toHaveBeenCalledTimes(before + 1);
  });
});
