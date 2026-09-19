import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "../usePolling";

describe("usePolling", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("does not call callback when disabled", () => {
    const cb = vi.fn();
    renderHook(() => usePolling(cb, 1000, false));
    act(() => { vi.advanceTimersByTime(3000); });
    expect(cb).not.toHaveBeenCalled();
  });

  it("calls callback at interval when enabled", () => {
    const cb = vi.fn();
    renderHook(() => usePolling(cb, 1000, true));
    act(() => { vi.advanceTimersByTime(3500); });
    expect(cb).toHaveBeenCalledTimes(3);
  });

  it("clears interval when disabled", () => {
    const cb = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) => usePolling(cb, 1000, enabled),
      { initialProps: { enabled: true } }
    );
    act(() => { vi.advanceTimersByTime(2500); });
    expect(cb).toHaveBeenCalledTimes(2);
    rerender({ enabled: false });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(cb).toHaveBeenCalledTimes(2);
  });

  it("clears interval on unmount", () => {
    const cb = vi.fn();
    const { unmount } = renderHook(() => usePolling(cb, 1000, true));
    act(() => { vi.advanceTimersByTime(1500); });
    expect(cb).toHaveBeenCalledTimes(1);
    unmount();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
