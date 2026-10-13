/** Horizontal windowing for a leaderboard with hundreds of columns (a run
 *  logging one metric per layer): only the sticky columns and the ones near
 *  the viewport render, the others collapse into one gap cell per side, so a
 *  row costs its visible cells rather than every column. */
import type { CSSProperties } from "react";
import { GAP_PREFIX } from "./leaderboardColumns";
import { layoutIds, type RowLayout } from "./LeaderboardRow";

export { isGapId } from "./leaderboardColumns";

/** Tables up to this many columns render whole, as before. */
export const WINDOW_MIN_COLS = 64;

/** Columns ``[start, end)`` to render besides the sticky ones. */
export interface ColRange {
  start: number;
  end: number;
}

function widthsOf(layout: RowLayout): number[] {
  return layout.widths ?? layout.styles.map((st) => Number.parseFloat(String(st.width ?? 0)) || 0);
}

function stickyCount(styles: readonly CSSProperties[]): number {
  let n = 0;
  while (n < styles.length && styles[n].position === "sticky") n += 1;
  return n;
}

/** The columns within about a viewport's width of the view at *scrollLeft*;
 *  null when the table is narrow enough to render whole. The window moves in
 *  half-viewport steps, so a small scroll keeps it (and the rows unrendered). */
export function visibleColumns(layout: RowLayout, scrollLeft: number, viewWidth: number): ColRange | null {
  const widths = widthsOf(layout);
  if (widths.length <= WINDOW_MIN_COLS) return null;
  const step = Math.max(1, viewWidth / 2);
  const at = Math.floor(scrollLeft / step) * step;
  const from = at - viewWidth;
  const to = at + step + 2 * viewWidth;
  let x = 0;
  let first = widths.length;
  let last = 0;
  widths.forEach((w, i) => {
    if (x + w > from && x < to) {
      first = Math.min(first, i);
      last = i + 1;
    }
    x += w;
  });
  const sticky = stickyCount(layout.styles);
  return { start: Math.max(sticky, first), end: last };
}

/** *layout* with the columns outside *range* folded into gap columns. */
export function windowLayout(layout: RowLayout, range: ColRange | null): RowLayout {
  if (range === null) return layout;
  const allIds = layoutIds(layout);
  const widths = widthsOf(layout);
  const sticky = stickyCount(layout.styles);
  const ids: string[] = [];
  const styles: CSSProperties[] = [];
  const kept: number[] = [];
  const take = (i: number) => {
    ids.push(allIds[i]);
    styles.push(layout.styles[i]);
    kept.push(widths[i]);
  };
  const gap = (side: string, from: number, to: number) => {
    const width = widths.slice(from, to).reduce((a, b) => a + b, 0);
    if (width <= 0) return;
    ids.push(`${GAP_PREFIX}${side}`);
    styles.push({ width: `${width}px` });
    kept.push(width);
  };
  for (let i = 0; i < sticky; i++) take(i);
  gap("left", sticky, range.start);
  for (let i = range.start; i < range.end; i++) take(i);
  gap("right", range.end, widths.length);
  return { ...layout, ids, styles, widths: kept };
}
