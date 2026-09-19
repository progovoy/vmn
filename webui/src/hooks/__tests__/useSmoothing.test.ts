import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { ema, useSmoothing } from "../useSmoothing";

describe("ema", () => {
  it("alpha=0 returns original data unchanged", () => {
    const data = [1, 2, 3, 4, 5];
    expect(ema(data, 0)).toEqual([1, 2, 3, 4, 5]);
  });

  it("alpha=0.9 produces correct EMA values", () => {
    const data = [10, 20, 30, 40, 50];
    const result = ema(data, 0.9);
    // smoothed[0] = 10
    // smoothed[1] = 0.9 * 10 + 0.1 * 20 = 11
    // smoothed[2] = 0.9 * 11 + 0.1 * 30 = 12.9
    // smoothed[3] = 0.9 * 12.9 + 0.1 * 40 = 15.61
    // smoothed[4] = 0.9 * 15.61 + 0.1 * 50 = 19.049
    expect(result).toHaveLength(5);
    expect(result[0]).toBeCloseTo(10);
    expect(result[1]).toBeCloseTo(11);
    expect(result[2]).toBeCloseTo(12.9);
    expect(result[3]).toBeCloseTo(15.61);
    expect(result[4]).toBeCloseTo(19.049);
  });

  it("empty input returns empty output", () => {
    expect(ema([], 0.5)).toEqual([]);
  });

  it("single point returns that point", () => {
    expect(ema([42], 0.9)).toEqual([42]);
  });
});

describe("useSmoothing", () => {
  it("returns a memoized smooth function", () => {
    const { result } = renderHook(() => useSmoothing(0.5));
    expect(typeof result.current).toBe("function");
  });

  it("smooth function applies ema correctly", () => {
    const { result } = renderHook(() => useSmoothing(0));
    expect(result.current([1, 2, 3])).toEqual([1, 2, 3]);
  });

  it("returns same function reference for same alpha", () => {
    const { result, rerender } = renderHook(
      ({ alpha }) => useSmoothing(alpha),
      { initialProps: { alpha: 0.5 } }
    );
    const first = result.current;
    rerender({ alpha: 0.5 });
    expect(result.current).toBe(first);
  });
});
