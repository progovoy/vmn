/** Plan 22 F10: the grouped board's count columns. */
import { describe, it, expect } from "vitest";
import {
  GROUP_COUNT_COLS, boardSort, countColumnVisible, groupCount, groupCountTone, headGroups, isGroupCountId,
} from "../groupCountColumns";

const counts = { total: 9, running: 2, waiting: 1, done: 3, failed: 1, stuck: 2 };

describe("the group count columns", () => {
  it("are total, waiting, running, done and failed, keyed c:<name>", () => {
    expect(GROUP_COUNT_COLS).toEqual(["total", "waiting", "running", "done", "failed"]);
    for (const c of GROUP_COUNT_COLS) expect(isGroupCountId(`c:${c}`)).toBe(true);
    for (const id of ["c:started", "c:stuck", "m:total", "total", "c:inner"]) expect(isGroupCountId(id)).toBe(false);
  });

  it("count a group's runs as the inner-run columns did: stuck goes with failed", () => {
    expect(GROUP_COUNT_COLS.map((c) => groupCount(counts, c))).toEqual([9, 1, 2, 3, 3]);
  });

  it("colour a non-zero count by its state and mute a zero", () => {
    expect(groupCountTone("failed", 3)).toBe("tone-failed");
    expect(groupCountTone("done", 1)).toBe("tone-done");
    expect(groupCountTone("running", 2)).toBe("tone-running");
    expect(groupCountTone("waiting", 1)).toBe("tone-waiting");
    expect(groupCountTone("total", 9)).toBe("tone-total");
    expect(groupCountTone("failed", 0)).toBe("count-zero");
  });

  it("show while grouped unless hide= names them, and never ungrouped", () => {
    const none = new Set<string>();
    expect(countColumnVisible("c:total", none, true)).toBe(true);
    expect(countColumnVisible("c:total", new Set(["c:total"]), true)).toBe(false);
    expect(countColumnVisible("c:waiting", new Set(["c:total"]), true)).toBe(true);
    expect(countColumnVisible("c:total", none, false)).toBe(false);
  });
});

describe("the header group over the count columns", () => {
  it("spans the contiguous count block and leaves every other column its own cell", () => {
    const ids = ["check", "idx", "status", "experiment", "c:total", "c:waiting", "c:running", "c:done",
      "c:failed", "c:started", "m:loss", "when"];
    expect(headGroups(ids)).toEqual([
      { start: 0, span: 1, counts: false }, { start: 1, span: 1, counts: false },
      { start: 2, span: 1, counts: false }, { start: 3, span: 1, counts: false },
      { start: 4, span: 5, counts: true },
      { start: 9, span: 1, counts: false }, { start: 10, span: 1, counts: false },
      { start: 11, span: 1, counts: false },
    ]);
  });

  it("labels each block again when a count column is dragged away from the rest", () => {
    const ids = ["experiment", "c:total", "c:waiting", "m:loss", "c:failed"];
    expect(headGroups(ids)!.filter((g) => g.counts)).toEqual([
      { start: 1, span: 2, counts: true }, { start: 4, span: 1, counts: true },
    ]);
  });

  it("gives a windowed table's gap column a cell of its own", () => {
    expect(headGroups(["experiment", "gap:left", "c:total", "c:waiting", "gap:right"])).toEqual([
      { start: 0, span: 1, counts: false }, { start: 1, span: 1, counts: false },
      { start: 2, span: 2, counts: true }, { start: 4, span: 1, counts: false },
    ]);
  });

  it("is absent without count columns", () => {
    expect(headGroups(["experiment", "c:started", "m:loss"])).toBeNull();
  });
});

describe("the board's sort", () => {
  it("keeps a count sort while grouped and drops it on the flat board", () => {
    expect(boardSort("c:total", "parent")).toBe("c:total");
    expect(boardSort("c:total", "none")).toBeNull();
    expect(boardSort("loss", "none")).toBe("loss");
    expect(boardSort(null, "parent")).toBeNull();
    // The grouping is not known yet: nothing is fetched, the sort stays.
    expect(boardSort("c:failed", null)).toBe("c:failed");
  });
});
