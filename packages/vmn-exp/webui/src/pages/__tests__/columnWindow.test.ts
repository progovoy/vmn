import { describe, it, expect } from "vitest";
import type { CSSProperties } from "react";
import { WINDOW_MIN_COLS, isGapId, visibleColumns, windowLayout } from "../columnWindow";
import type { RowLayout } from "../LeaderboardRow";

function layoutOf(n: number, sticky = 2, width = 100): RowLayout {
  const ids = Array.from({ length: n }, (_, i) => (i < sticky ? `s${i}` : `m:k${i}`));
  const styles: CSSProperties[] = ids.map((_, i) =>
    i < sticky ? { width: `${width}px`, position: "sticky", left: i * width } : { width: `${width}px` });
  return {
    ids, styles, widths: ids.map(() => width), total: n * width,
    metricCols: [], paramCols: [], colMeta: {}, showBest: false, runBase: "/ws/w/app/a",
  };
}

const sum = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0);

describe("column window", () => {
  it("leaves a table of ordinary width alone", () => {
    const layout = layoutOf(WINDOW_MIN_COLS);
    const range = visibleColumns(layout, 0, 1000);
    expect(range).toBeNull();
    expect(windowLayout(layout, range)).toBe(layout);
  });

  it("keeps the sticky columns and the ones in view, the rest as one gap", () => {
    const layout = layoutOf(600);
    const windowed = windowLayout(layout, visibleColumns(layout, 0, 1000));
    const ids = windowed.ids!;
    expect(ids.slice(0, 2)).toEqual(["s0", "s1"]);
    expect(ids).toContain("m:k2");
    expect(ids).toContain("m:k11");
    expect(ids.length).toBeLessThan(80);
    expect(isGapId(ids[ids.length - 1])).toBe(true);
    expect(ids.filter(isGapId)).toHaveLength(1);
    expect(windowed.total).toBe(layout.total);
    expect(sum(windowed.widths!)).toBe(layout.total);
    expect(windowed.styles).toHaveLength(ids.length);
  });

  it("follows a horizontal scroll with a gap on either side", () => {
    const layout = layoutOf(600);
    const windowed = windowLayout(layout, visibleColumns(layout, 30_000, 1000));
    const ids = windowed.ids!;
    expect(ids.slice(0, 2)).toEqual(["s0", "s1"]);
    expect(isGapId(ids[2])).toBe(true);
    expect(ids).toContain("m:k300");
    expect(ids).not.toContain("m:k100");
    expect(isGapId(ids[ids.length - 1])).toBe(true);
    expect(sum(windowed.widths!)).toBe(layout.total);
    expect(windowed.styles[2].width).toBe(`${windowed.widths![2]}px`);
  });

  it("moves in steps, so a small scroll keeps the same window", () => {
    const layout = layoutOf(600);
    expect(visibleColumns(layout, 30_000, 1000)).toEqual(visibleColumns(layout, 30_040, 1000));
  });
  it("takes a range computed for an earlier, wider layout without inventing columns", () => {
    // The table renders a changed layout once before its effect re-reads the window.
    const stale = visibleColumns(layoutOf(600), 0, 3000)!;
    const narrow = layoutOf(20);
    expect(windowLayout(narrow, stale)).toBe(narrow);
    const wide = layoutOf(100);
    const windowed = windowLayout(wide, visibleColumns(layoutOf(600), 30_000, 1000));
    expect(windowed.styles.every(Boolean)).toBe(true);
    expect(windowed.ids!.every(Boolean)).toBe(true);
    expect(sum(windowed.widths!)).toBe(wide.total);
  });
});
