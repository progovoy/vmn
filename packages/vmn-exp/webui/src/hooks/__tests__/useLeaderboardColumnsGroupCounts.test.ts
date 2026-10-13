/** Plan 22 F10: the grouped board's count columns among the leaderboard's columns. */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import type { ExperimentRow } from "../../types";

const row = (i: number): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics: { loss: i },
});
const COUNTS = ["c:total", "c:waiting", "c:running", "c:done", "c:failed"];
const PREFS = { widths: {}, order: [] as readonly string[] };

function columns(grouped: boolean, hidden = new Set<string>(), shown = new Set<string>()) {
  const { result } = renderHook(() => useLeaderboardColumns(
    [row(1), row(2)], { loss: { goal: "min" } }, hidden, "", null, [], [], PREFS, 0, shown, grouped,
  ));
  return result.current;
}

describe("the group count columns (plan 22 F10)", () => {
  it("show while grouped, in order, right after the pinned columns", () => {
    const ids = columns(true).layout.ids ?? [];
    expect(ids.filter((id) => COUNTS.includes(id))).toEqual(COUNTS);
    const at = ids.indexOf("c:total");
    expect(ids.slice(at, at + 5)).toEqual(COUNTS);
    expect(ids[at - 1]).toBe("m:loss");
  });

  it("are absent from the flat board and from its column picker, even with show=", () => {
    const c = columns(false, new Set(), new Set(COUNTS));
    expect((c.layout.ids ?? []).filter((id) => COUNTS.includes(id))).toEqual([]);
    for (const n of ["total", "waiting", "running", "done", "failed"]) expect(c.otherCols).not.toContain(n);
  });

  it("are offered in the column picker while grouped, each hideable with hide=", () => {
    const c = columns(true, new Set(["c:running"]));
    expect(c.otherCols).toEqual(expect.arrayContaining(["total", "waiting", "running", "done", "failed"]));
    expect(c.visibleOther).toEqual(expect.arrayContaining(["total", "waiting", "done", "failed"]));
    expect(c.visibleOther).not.toContain("running");
    expect(c.layout.ids).not.toContain("c:running");
    expect(c.layout.fleetCols).toEqual(["total", "waiting", "done", "failed"]);
  });
});
