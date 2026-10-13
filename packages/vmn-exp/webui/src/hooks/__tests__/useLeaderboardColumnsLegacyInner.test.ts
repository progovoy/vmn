/** The five inner-count columns (`c:total`, `c:waiting`, `c:running`,
 *  `c:done`, `c:failed`) were one `c:inner` column for a while (plan 20 C2,
 *  reverted by the user on 2026-10-13); links and views saved then name
 *  `c:inner`, which now means all five. */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import type { ExperimentRow } from "../../types";

const row = (i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics: { loss: i }, ...extra,
});
const OUTER = [row(1, { kind: "outer", children: ["v2"] }), row(2, { kind: "inner", parent: "v1" })];
const SINGLE = [row(1)];
const COUNTS = ["c:total", "c:waiting", "c:running", "c:done", "c:failed"];
const PREFS = { widths: {}, order: [] as readonly string[] };

function counts(rows: ExperimentRow[], hidden: Iterable<string> = [], shown: Iterable<string> = []) {
  const { result } = renderHook(() => useLeaderboardColumns(
    rows, null, new Set(hidden), "", null, [], [], PREFS, 0, new Set(shown),
  ));
  return (result.current.layout.ids ?? []).filter((id) => COUNTS.includes(id));
}

describe("the inner-count columns", () => {
  it("all show while an outer run is loaded, none without one", () => {
    expect(counts(OUTER)).toEqual(COUNTS);
    expect(counts(SINGLE)).toEqual([]);
  });

  it("hide one by one with their own hide= keys", () => {
    expect(counts(OUTER, ["c:waiting", "c:done"])).toEqual(["c:total", "c:running", "c:failed"]);
  });

  it("show one by one with their own show= keys", () => {
    expect(counts(SINGLE, [], ["c:total"])).toEqual(["c:total"]);
  });
});

describe("a c:inner key from the single inner column", () => {
  it("hides all five", () => {
    expect(counts(OUTER, ["c:inner"])).toEqual([]);
  });

  it("shows all five", () => {
    expect(counts(SINGLE, [], ["c:inner"])).toEqual(COUNTS);
  });

  it("gives way to a count's own key", () => {
    expect(counts(OUTER, ["c:inner"], ["c:running"])).toEqual(["c:running"]);
    expect(counts(SINGLE, ["c:total"], ["c:inner"])).toEqual(["c:waiting", "c:running", "c:done", "c:failed"]);
  });

  it("leaves the inner column itself out of the table", () => {
    const { result } = renderHook(() => useLeaderboardColumns(
      OUTER, null, new Set(), "", null, [], [], PREFS, 0, new Set(["c:inner"]),
    ));
    expect(result.current.layout.ids).not.toContain("c:inner");
    expect(result.current.otherCols).not.toContain("inner");
  });
});
