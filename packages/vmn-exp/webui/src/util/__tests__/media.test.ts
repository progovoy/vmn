import { describe, expect, it } from "vitest";
import { hasMedia, histogramBars, histogramRange, tablePageUrl } from "../media";

const H = [
  { step: 0, bins: [0, 1, 2], counts: [1, 3] },
  { step: 5, bins: [-1, 1, 4], counts: [2, 0] },
];

describe("histogramBars", () => {
  it("lays bins out by their edges, heights relative to the tallest", () => {
    const bars = histogramBars(H[0], 100, 50);
    expect(bars).toHaveLength(2);
    expect(bars[0]).toMatchObject({ x: 0, w: 50, h: 50 / 3, count: 1, lo: 0, hi: 1 });
    expect(bars[1]).toMatchObject({ x: 50, w: 50, h: 50, count: 3 });
    expect(bars[1].y).toBe(0);
  });

  it("uses a shared x range when given one", () => {
    const bars = histogramBars(H[0], 100, 10, [-2, 2]);
    expect(bars[0].x).toBe(50);
    expect(bars[1].x + bars[1].w).toBe(100);
  });

  it("an all-zero histogram has flat bars", () => {
    expect(histogramBars({ step: 0, bins: [0, 1], counts: [0] }, 10, 10)[0].h).toBe(0);
  });
});

describe("histogramRange", () => {
  it("spans every step's edges", () => {
    expect(histogramRange(H)).toEqual([-1, 4]);
  });
});

describe("hasMedia", () => {
  it("is false for missing or empty indexes", () => {
    expect(hasMedia({})).toBe(false);
    expect(hasMedia({ media: {}, tables: {}, histograms: {} })).toBe(false);
    expect(hasMedia({ tables: { t: [] }, media: {} })).toBe(true);
  });
});

describe("tablePageUrl", () => {
  it("encodes the path and page parameters", () => {
    const url = tablePageUrl("ws", "a/b", "1.0.0-dev.x", "tables/my t/0.json", {
      offset: 20, limit: 10, sort: "loss", order: "desc",
    });
    expect(url).toBe(
      "/workspaces/ws/apps/a-b/experiments/1.0.0-dev.x/table/tables/my%20t/0.json" +
        "?offset=20&limit=10&sort=loss&order=desc",
    );
  });

  it("leaves sort out when unsorted", () => {
    expect(tablePageUrl("ws", "a", "v", "tables/t/0.json", { offset: 0, limit: 5 }))
      .toBe("/workspaces/ws/apps/a/experiments/v/table/tables/t/0.json?offset=0&limit=5");
  });
});
