import { describe, it, expect } from "vitest";
import { columnLayout, columnStyles, EXPERIMENT_COL_INDEX } from "../leaderboardColumns";
import type { ColumnCell } from "../leaderboardColumns";

// Fixed widths: check=34, idx=56, status=110 → stickyLeft = 200
const STICKY_LEFT = 34 + 56 + 110;

describe("columnStyles pinnedCount", () => {
  it("zero pinnedCount: only the experiment column is sticky", () => {
    const cells: ColumnCell[] = [
      { kind: "metric", key: "loss" },
      { kind: "metric", key: "acc" },
    ];
    const layout = columnLayout(cells, false);
    const styles = columnStyles(layout, 0);
    expect(styles[EXPERIMENT_COL_INDEX].position).toBe("sticky");
    // metric cells (indices 4, 5) have no position
    expect((styles[4] as Record<string, unknown>).position).toBeUndefined();
    expect((styles[5] as Record<string, unknown>).position).toBeUndefined();
  });

  it("pinnedCount=1: first metric/param column gets sticky with correct left", () => {
    const cells: ColumnCell[] = [
      { kind: "metric", key: "loss" },
      { kind: "metric", key: "acc" },
    ];
    const layout = columnLayout(cells, false);
    const expWidth = layout.widths[EXPERIMENT_COL_INDEX];
    const styles = columnStyles(layout, 1);
    expect(styles[4].position).toBe("sticky");
    expect(styles[4].left).toBe(STICKY_LEFT + expWidth);
    expect((styles[5] as Record<string, unknown>).position).toBeUndefined();
  });

  it("pinnedCount=2: two pinned columns get cumulative sticky left offsets", () => {
    // metric width = 110, param width = 120
    const cells: ColumnCell[] = [
      { kind: "metric", key: "loss" }, // index 4
      { kind: "param", key: "lr" },   // index 5
      { kind: "metric", key: "acc" }, // index 6
    ];
    const layout = columnLayout(cells, false);
    const expWidth = layout.widths[EXPERIMENT_COL_INDEX];
    const base = STICKY_LEFT + expWidth;
    const styles = columnStyles(layout, 2);
    expect(styles[4].position).toBe("sticky");
    expect(styles[4].left).toBe(base);
    expect(styles[5].position).toBe("sticky");
    expect(styles[5].left).toBe(base + 110); // metric width = 110
    expect((styles[6] as Record<string, unknown>).position).toBeUndefined();
  });

  it("unpinned columns have no position property", () => {
    const cells: ColumnCell[] = [{ kind: "param", key: "lr" }];
    const layout = columnLayout(cells, false);
    const styles = columnStyles(layout, 0);
    expect((styles[4] as Record<string, unknown>).position).toBeUndefined();
  });
});
