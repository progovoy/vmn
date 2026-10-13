/** Plan 22 F10, F13: the grouped board's sort of groups by a count. */
import { describe, it, expect } from "vitest";
import { GROUP_SORTS, boardSort, groupSortOf, isGroupCountId } from "../groupCountSort";

describe("the count sorts", () => {
  it("are total, running, failed, waiting and done, keyed c:<name>", () => {
    for (const c of ["total", "waiting", "running", "done", "failed"]) expect(isGroupCountId(`c:${c}`)).toBe(true);
    for (const id of ["c:started", "c:stuck", "m:total", "total", "c:inner", null, undefined]) {
      expect(isGroupCountId(id)).toBe(false);
    }
  });

  it("offer the aggregate first, then each count by how a person says it", () => {
    expect(GROUP_SORTS.map((s) => [s.value, s.label])).toEqual([
      [null, "aggregate"], ["c:total", "runs"], ["c:running", "running"], ["c:failed", "failed"],
      ["c:waiting", "waiting"], ["c:done", "succeeded"],
    ]);
  });

  it("read the board's sort as a group sort: a count, else the aggregate", () => {
    expect(groupSortOf("c:failed")).toBe("c:failed");
    expect(groupSortOf("val_loss")).toBeNull();
    expect(groupSortOf(null)).toBeNull();
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
