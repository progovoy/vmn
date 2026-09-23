import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "../hooks/usePolling";

describe("usePolling never overlaps requests", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("waits for a slow request to settle before scheduling the next", async () => {
    let resolve: () => void = () => {};
    const cb = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    renderHook(() => usePolling(cb, 1000, true));

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(cb).toHaveBeenCalledTimes(1);
    // Still in flight: no new poll however long the request takes.
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(cb).toHaveBeenCalledTimes(1);

    await act(async () => { resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(999); });
    expect(cb).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(cb).toHaveBeenCalledTimes(2);
  });

  it("keeps polling after a request fails", async () => {
    const cb = vi.fn(() => Promise.reject(new Error("boom")));
    renderHook(() => usePolling(cb, 1000, true));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(cb).toHaveBeenCalledTimes(2);
  });
});
