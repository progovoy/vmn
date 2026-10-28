/** Plan 28 P1: an outer run's page reads the status of its subtree
 *  (`experiments-status?scope=`), keyed apart from the app's and polled. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createQueryClient } from "../../queryClient";
import type { AppStatus } from "../contracts";

const appStatus = vi.fn();
vi.mock("../../apiShell", () => ({
  apiShell: { appStatus: (...args: unknown[]) => appStatus(...args) },
}));

import { useAppStatus, useScopedStatus } from "../useShellData";

const status = (stuck: number): AppStatus => ({
  total: 1, counts: { created: 0, running: 0, stuck, succeeded: 0, failed: 0 }, failed_recent: 0, rollup: null,
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;

beforeEach(() => {
  client = createQueryClient();
  appStatus.mockReset();
});

describe("useScopedStatus", () => {
  it("asks for the scope's status, cached apart from the app's", async () => {
    appStatus.mockImplementation((_ws: string, _tag: string, scope?: string) => Promise.resolve(status(scope ? 2 : 9)));
    const app = renderHook(() => useAppStatus("w", "a"), { wrapper });
    const scoped = renderHook(() => useScopedStatus("w", "a", "0.0.1-dev.x"), { wrapper });
    await waitFor(() => expect(scoped.result.current.data).toEqual(status(2)));
    await waitFor(() => expect(app.result.current.data).toEqual(status(9)));
    expect(appStatus).toHaveBeenCalledWith("w", "a", "0.0.1-dev.x");
  });

  it("waits for a scope", async () => {
    renderHook(() => useScopedStatus("w", "a", undefined), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(appStatus).not.toHaveBeenCalled();
  });

  describe("polling", () => {
    beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
    afterEach(() => vi.useRealTimers());

    it("refetches on the status cadence (fast while a run is stuck)", async () => {
      appStatus.mockResolvedValue(status(1));
      renderHook(() => useScopedStatus("w", "a", "v"), { wrapper });
      await waitFor(() => expect(appStatus).toHaveBeenCalledTimes(1));
      await act(async () => { await vi.advanceTimersByTimeAsync(15_500); });
      expect(appStatus).toHaveBeenCalledTimes(2);
    });
  });
});
