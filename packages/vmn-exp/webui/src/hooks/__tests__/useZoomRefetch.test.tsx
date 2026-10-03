import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useZoomRefetch, ZOOM_DEBOUNCE_MS } from "../useZoomRefetch";
import type { SeriesPoint } from "../../types";

const pts = (steps: number[]): SeriesPoint[] => steps.map((step) => ({ step, value: 1, ts: null }));

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

const flush = async () => { await act(async () => { await Promise.resolve(); }); };

describe("useZoomRefetch", () => {
  it("debounces zooms and fetches only the last range", async () => {
    const fetchRange = vi.fn().mockResolvedValue(pts([10, 11]));
    const { result } = renderHook(() => useZoomRefetch("loss", fetchRange));
    act(() => { result.current.onXRange([0, 50]); result.current.onXRange([10, 20]); });
    expect(fetchRange).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    expect(fetchRange).toHaveBeenCalledTimes(1);
    expect(fetchRange).toHaveBeenCalledWith("loss", 10, 20);
    expect(result.current.zoom).toBeNull(); // the coarse series stays meanwhile
    expect(result.current.loading).toBe(true);
    await flush();
    expect(result.current.zoom).toEqual({ range: [10, 20], points: pts([10, 11]) });
    expect(result.current.loading).toBe(false);
  });

  it("drops a response a newer zoom superseded, and clears on reset", async () => {
    let resolveFirst: (p: SeriesPoint[]) => void = () => {};
    const fetchRange = vi.fn()
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValueOnce(pts([30]));
    const { result } = renderHook(() => useZoomRefetch("loss", fetchRange));
    act(() => { result.current.onXRange([10, 20]); vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    act(() => { result.current.onXRange([25, 35]); vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    await flush();
    resolveFirst(pts([10]));
    await flush();
    expect(result.current.zoom?.range).toEqual([25, 35]);
    act(() => result.current.onXRange(null));
    expect(result.current.zoom).toBeNull();
  });

  it("ignores a repeat of the current range and does nothing without a fetcher", () => {
    const fetchRange = vi.fn().mockResolvedValue([]);
    const { result } = renderHook(() => useZoomRefetch("loss", fetchRange));
    act(() => { result.current.onXRange([1, 2]); vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    act(() => { result.current.onXRange([1, 2]); vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    expect(fetchRange).toHaveBeenCalledTimes(1);
    const none = renderHook(() => useZoomRefetch("loss", undefined));
    act(() => { none.result.current.onXRange([1, 2]); vi.advanceTimersByTime(ZOOM_DEBOUNCE_MS); });
    expect(none.result.current.zoom).toBeNull();
  });
});
