import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { AppStatus, GitContext } from "../contracts";

const meta = vi.fn();
const gitContext = vi.fn();
const appStatus = vi.fn();
vi.mock("../../api", () => ({ api: { meta: () => meta() } }));
vi.mock("../../apiShell", () => ({
  apiShell: {
    gitContext: (ws: string) => gitContext(ws),
    appStatus: (ws: string, tag: string) => appStatus(ws, tag),
  },
}));

import { statusPollMs, useAppStatus, useAppStatusPoll, useGitContext } from "../useShellData";

const GIT: GitContext = {
  branch: "main", detached: false, head: null, head_short: null, dirty: false, store: ".vmn/store",
};
const status = (running: number, stuck: number): AppStatus => ({
  total: 1, counts: { created: 0, running, stuck, succeeded: 0, failed: 0 },
  failed_recent: 0, rollup: null,
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;

describe("useShellData", () => {
  beforeEach(() => {
    client = createQueryClient();
    [meta, gitContext, appStatus].forEach((f) => f.mockReset());
  });

  it("useGitContext asks only when enabled and a workspace is known", async () => {
    gitContext.mockResolvedValue(GIT);
    renderHook(() => useGitContext("team", false), { wrapper });
    renderHook(() => useGitContext(undefined, true), { wrapper });
    const { result } = renderHook(() => useGitContext("ml-repo", true), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(GIT));
    expect(gitContext.mock.calls).toEqual([["ml-repo"]]);
    expect(client.getQueryData(["git", "ml-repo"])).toEqual(GIT);
  });

  it("useAppStatus keys by workspace and tag", async () => {
    appStatus.mockResolvedValue(status(0, 0));
    renderHook(() => useAppStatus("w", undefined), { wrapper });
    const { result } = renderHook(() => useAppStatus("w", "root-svc"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(status(0, 0)));
    expect(appStatus.mock.calls).toEqual([["w", "root-svc"]]);
    expect(client.getQueryData(["app-status", "w", "root-svc"])).toEqual(status(0, 0));
  });

  it("a failure stays in the result instead of throwing", async () => {
    appStatus.mockRejectedValue(Object.assign(new Error("x"), { status: 500 }));
    const { result } = renderHook(() => useAppStatus("w", "a"), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it.each([
    [undefined, 60_000],
    [status(0, 0), 60_000],
    [status(2, 0), 15_000],
    [status(0, 1), 15_000],
  ])("polls status every %#", (s, ms) => {
    expect(statusPollMs(s)).toBe(ms);
  });
});

describe("app status polling", () => {
  beforeEach(() => {
    client = createQueryClient();
    appStatus.mockReset();
    appStatus.mockResolvedValue(status(1, 0));
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

  it("a plain reader never polls, however many there are", async () => {
    renderHook(() => useAppStatus("w", "a"), { wrapper });
    renderHook(() => useAppStatus("w", "a"), { wrapper });
    await waitFor(() => expect(appStatus).toHaveBeenCalledTimes(1));
    await advance(61_000);
    expect(appStatus).toHaveBeenCalledTimes(1);
  });

  it("the one poller refetches on the status cadence for every reader", async () => {
    const reader = renderHook(() => useAppStatus("w", "a"), { wrapper });
    renderHook(() => useAppStatusPoll("w", "a"), { wrapper });
    await waitFor(() => expect(appStatus).toHaveBeenCalledTimes(1));
    appStatus.mockResolvedValue(status(0, 0));
    await advance(15_500);
    expect(appStatus).toHaveBeenCalledTimes(2);
    expect(reader.result.current.data).toEqual(status(0, 0));
  });

  it("a reader mounting within 10 s reads the cache without a refetch", async () => {
    renderHook(() => useAppStatus("w", "a"), { wrapper });
    await waitFor(() => expect(appStatus).toHaveBeenCalledTimes(1));
    await advance(5_000);
    renderHook(() => useAppStatus("w", "a"), { wrapper });
    await advance(10);
    expect(appStatus).toHaveBeenCalledTimes(1);
  });
});
