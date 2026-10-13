/** Saved views and links from before plan 20 C2 name the five inner-count
 *  columns (`c:total`, `c:waiting`, `c:running`, `c:done`, `c:failed`); they
 *  now mean the one inner column, `c:inner`. */
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
const none = new Set<string>();
const PREFS = { widths: {}, order: [] as readonly string[] };

function fleet(rows: ExperimentRow[], hidden: Iterable<string> = [], shown: Iterable<string> = []) {
  const { result } = renderHook(() => useLeaderboardColumns(
    rows, null, new Set(hidden), "", null, [], [], PREFS, 0, new Set(shown),
  ));
  return result.current.layout.ids ?? [];
}

describe("legacy inner-count keys", () => {
  it("hide the inner column when an old view hid every count column", () => {
    expect(fleet(OUTER)).toContain("c:inner");
    expect(fleet(OUTER, COUNTS)).not.toContain("c:inner");
  });

  it("keep the inner column while an old view hid only some counts", () => {
    expect(fleet(OUTER, ["c:waiting", "c:done"])).toContain("c:inner");
  });

  it("show the inner column for an old show= of a count column", () => {
    expect(fleet(SINGLE, [], none)).not.toContain("c:inner");
    expect(fleet(SINGLE, [], ["c:total"])).toContain("c:inner");
  });

  it("let an explicit hide of the inner column beat an old show= of a count", () => {
    expect(fleet(SINGLE, ["c:inner"], ["c:total"])).not.toContain("c:inner");
    expect(fleet(OUTER, ["c:inner"], ["c:running"])).not.toContain("c:inner");
  });

  it("let an explicit show of the inner column beat an old hide= of every count", () => {
    expect(fleet(OUTER, COUNTS, ["c:inner"])).toContain("c:inner");
  });
});
