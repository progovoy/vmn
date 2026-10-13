/** Plan 23 W3: a numeric param's facet is a mini histogram whose bars are
 *  range clauses. */
import { describe, it, expect } from "vitest";
import { binClauses, numericBins, numericKeys } from "../facetBins";

describe("numericBins", () => {
  it("counts finite numbers into equal-width bins, the last one closed", () => {
    const bins = numericBins([0, 1, 2, 3, 4, 10, null, "x", Number.NaN], 5);
    expect(bins.map((b) => [b.lo, b.hi, b.count])).toEqual([
      [0, 2, 2], [2, 4, 2], [4, 6, 1], [6, 8, 0], [8, 10, 1],
    ]);
    expect(bins.map((b) => b.last)).toEqual([false, false, false, false, true]);
  });

  it("is one bin for a single value, and none without numbers", () => {
    expect(numericBins([3, 3, 3], 5)).toEqual([{ lo: 3, hi: 3, count: 3, last: true }]);
    expect(numericBins(["a", null], 5)).toEqual([]);
  });

  it("rounds the edges to readable numbers", () => {
    const bins = numericBins([0, 0.1, 0.3], 3);
    expect(bins.map((b) => b.hi)).toEqual([0.1, 0.2, 0.3]);
    expect(bins.map((b) => b.count)).toEqual([1, 1, 1]);
  });
});

describe("binClauses", () => {
  it("is a half-open range, closed for the last bin and equality for a point", () => {
    expect(binClauses("params.lr", { lo: 0, hi: 2, count: 1, last: false })).toEqual(["params.lr >= 0", "params.lr < 2"]);
    expect(binClauses("params.lr", { lo: 8, hi: 10, count: 1, last: true })).toEqual(["params.lr >= 8", "params.lr <= 10"]);
    expect(binClauses("params.lr", { lo: 3, hi: 3, count: 3, last: true })).toEqual(["params.lr = 3"]);
  });
});

describe("numericKeys", () => {
  it("is the keys as numbers when every one is a number", () => {
    expect(numericKeys(["1", "0.5", "-2e-3"])).toEqual([1, 0.5, -0.002]);
    expect(numericKeys(["1", "adam"])).toBeNull();
    expect(numericKeys([])).toBeNull();
  });
});
