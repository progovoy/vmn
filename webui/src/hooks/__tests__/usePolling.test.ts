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

/** A backgrounded tab must not keep hammering the server. */
describe("usePolling visibility gate", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  const setVisibility = (state: DocumentVisibilityState) =>
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => state,
    });

  it("does not poll while the tab is hidden", () => {
    setVisibility("hidden");
    const cb = vi.fn();
    renderHook(() => usePolling(cb, 1000, true));
    act(() => { vi.advanceTimersByTime(3500); });
    expect(cb).not.toHaveBeenCalled();
  });

  it("resumes when the tab becomes visible again", () => {
    setVisibility("hidden");
    const cb = vi.fn();
    renderHook(() => usePolling(cb, 1000, true));
    act(() => { vi.advanceTimersByTime(3500); });
    expect(cb).not.toHaveBeenCalled();

    setVisibility("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    act(() => { vi.advanceTimersByTime(2500); });
    expect(cb).toHaveBeenCalledTimes(2);
  });

  it("stops polling when the tab is hidden mid-flight", () => {
    const cb = vi.fn();
    renderHook(() => usePolling(cb, 1000, true));
    act(() => { vi.advanceTimersByTime(1500); });
    expect(cb).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
