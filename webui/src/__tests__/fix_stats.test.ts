import { describe, it, expect } from "vitest";
import { finiteNumbers, maxOf, minOf } from "../util/stats";

describe("stats helpers", () => {
  it("handles arrays far beyond the spread-argument limit", () => {
    const big = Array.from({ length: 300_000 }, (_, i) => i);
    expect(minOf(big)).toBe(0);
    expect(maxOf(big)).toBe(299_999);
  });

  it("ignores null, NaN, infinities and non-numbers", () => {
    const vals = [3, null, NaN, Infinity, -Infinity, "x", undefined, 1, 2];
    expect(finiteNumbers(vals)).toEqual([3, 1, 2]);
    expect(minOf(vals)).toBe(1);
    expect(maxOf(vals)).toBe(3);
  });

  it("returns NaN for an empty or all-invalid input", () => {
    expect(minOf([])).toBeNaN();
    expect(maxOf([null, NaN])).toBeNaN();
  });
});
