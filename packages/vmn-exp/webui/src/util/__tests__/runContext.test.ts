/** Plan 23 W7: the order a job's Runs tab showed, carried to a run page. */
import { describe, it, expect } from "vitest";
import { betterClause, decodeFrom, defaultOrder, encodeFrom, histMarkAt, runContextSearch } from "../runContext";

describe("the board order a run link carries", () => {
  const order = { scope: "J", q: "metrics.loss < 1", status: "succeeded", sort: "loss", order: "asc" as const };

  it("round-trips through from= and at=", () => {
    const search = new URLSearchParams(runContextSearch(order, 4));
    expect(search.get("at")).toBe("4");
    expect(decodeFrom(search.get("from"), "J")).toEqual(order);
  });

  it("leaves out empty filters", () => {
    expect(encodeFrom({ scope: "J", sort: "idx" })).toBe("scope=J&sort=idx");
  });

  it("ignores an order of another job, or none", () => {
    expect(decodeFrom(encodeFrom(order), "K")).toBeNull();
    expect(decodeFrom(null, "J")).toBeNull();
  });

  it("falls back to the job's default order: newest first", () => {
    expect(defaultOrder("J")).toEqual({ scope: "J", sort: "idx" });
  });
});

describe("betterClause", () => {
  it("selects the runs better than a value on the metric's goal", () => {
    expect(betterClause("val_loss", 0.25, "min")).toBe("metrics.val_loss < 0.25");
    expect(betterClause("acc", 0.9, "max")).toBe("metrics.acc > 0.9");
  });
});

describe("histMarkAt", () => {
  it("places a value along the histogram's span, clamped", () => {
    const bins = [{ lo: 0, hi: 1, count: 2 }, { lo: 1, hi: 2, count: 1 }];
    expect(histMarkAt(bins, 0.5)).toBe(0.25);
    expect(histMarkAt(bins, 5)).toBe(1);
    expect(histMarkAt([], 1)).toBeNull();
  });
});
