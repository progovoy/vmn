/** Plan 28 N2: what a pivot heatmap's cell says, how dark it is, where it links. */
import { describe, it, expect } from "vitest";
import type { Pivot, PivotCell } from "../../apiPivot";
import {
  cellFill, cellLabel, cellQuery, cellText, defaultAxes, fieldOptions, pivotRange, withQuery,
} from "../pivotCells";

const cell = (over: Partial<PivotCell> = {}): PivotCell => ({ n: 4, value: 4, clause: 'tags.d = "x"', ...over });

function pivot(over: Partial<Pivot> = {}): Pivot {
  return {
    rows: [{ key: "d1", label: "d1", n: 6, clause: 'tags.date = "d1"' }],
    cols: [{ key: "g1", label: "g1", n: 4, clause: 'tags.group = "g1"' },
      { key: "g2", label: "g2", n: 2, clause: 'tags.group = "g2"' }],
    cells: [[cell({ n: 4, value: 4 }), cell({ n: 2, value: 2 })]],
    total: 6, rows_total: 1, cols_total: 2, cell: "count", match: null, metric: null, agg: null,
    ...over,
  };
}

describe("pivot cells", () => {
  it("says a count, a share and an aggregate", () => {
    expect(cellText(cell({ n: 1234, value: 1234 }), "count")).toBe("1,234");
    expect(cellText(cell({ value: 0.125, hits: 1, n: 8 }), "share")).toBe("13%");
    expect(cellText(cell({ value: 0.48213 }), "agg")).toBe("0.4821");
    expect(cellText(cell({ value: null }), "agg")).toBe("–");
  });

  it("ranges a count or an aggregate over its cells, a share over 0..1", () => {
    expect(pivotRange(pivot())).toEqual([2, 4]);
    expect(pivotRange(pivot({ cell: "share" }))).toEqual([0, 1]);
    expect(pivotRange(pivot({ cells: [[null, cell({ value: null })]] }))).toEqual([null, null]);
  });

  it("fills one hue, light to dark with the value, its ink a text token", () => {
    const low = cellFill(2, [2, 4]);
    const high = cellFill(4, [2, 4]);
    expect(low.background).toMatch(/color-mix\(in srgb, var\(--accent\) \d+%, var\(--panel\)\)/);
    expect(parseInt(high.background.match(/(\d+)%/)![1])).toBeGreaterThan(parseInt(low.background.match(/(\d+)%/)![1]));
    expect(low.color).toBe("var(--text)");
    expect(high.color).toBe("var(--bg)");
    expect(cellFill(3, [3, 3]).color).toBe("var(--bg)");
    expect(cellFill(null, [2, 4]).background).toBe("var(--panel-2)");
  });

  it("names a cell for a screen reader and a tooltip", () => {
    const p = pivot({ cell: "share", match: 'tags.health = "unstable"' });
    expect(cellLabel(p, "tags.date", "tags.group", 0, 1, cell({ n: 8, hits: 2, value: 0.25 })))
      .toBe('tags.date d1, tags.group g2: 25% match tags.health = "unstable" (2 of 8 runs)');
    const agg = pivot({ cell: "agg", metric: "loss", agg: "median" });
    expect(cellLabel(agg, "tags.date", "tags.group", 0, 0, cell({ n: 3, value: 0.5 })))
      .toBe("tags.date d1, tags.group g1: median loss 0.5 (3 runs)");
  });

  it("links a cell to its runs, a share cell to its matching ones, under the panel's query", () => {
    const share = pivot({ cell: "share", match: 'tags.h = "u"' });
    expect(cellQuery(share, cell({ clause: 'a = 1' }))).toBe('a = 1 and (tags.h = "u")');
    expect(cellQuery(pivot(), cell({ clause: 'a = 1' }))).toBe("a = 1");
    expect(cellQuery(pivot(), cell({ clause: null }))).toBeNull();
    expect(withQuery("status = \"failed\"", "a = 1")).toBe('(status = "failed") and a = 1');
    expect(withQuery(undefined, "a = 1")).toBe("a = 1");
    expect(withQuery("  ", "a = 1")).toBe("a = 1");
  });

  it("offers tags, params and their ancestors' as fields, tags first", () => {
    const fields = fieldOptions({ tag_keys: ["date", "group"], param_keys: ["lr"] });
    expect(fields).toEqual(["tags.date", "tags.group", "params.lr", "status", "branch",
      "up.tags.date", "up.tags.group", "up.params.lr"]);
    expect(defaultAxes(fields)).toEqual(["tags.date", "tags.group"]);
    expect(defaultAxes(["params.lr", "status", "branch"])).toEqual(["params.lr", "status"]);
  });
});
