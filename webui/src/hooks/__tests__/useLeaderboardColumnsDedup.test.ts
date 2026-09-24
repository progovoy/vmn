import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import type { ExperimentRow } from "../../types";

function row(
  idx: number,
  metrics: Record<string, number>,
  params: Record<string, unknown>,
): ExperimentRow {
  return {
    idx, verstr: `v${idx}`, code_verstr: `v${idx}`, timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", user_meta: null, params, metrics,
  };
}

// A numeric param (e.g. `lr`) folds into `metrics` too — server-side and
// intentional (see CLAUDE.md) — so it shows up in both `r.params` and
// `r.metrics`. The leaderboard's column list must show it once.
const ROWS = [
  row(1, { loss: 0.5, lr: 0.01 }, { lr: 0.01 }),
  row(2, { loss: 0.3, lr: 0.02 }, { lr: 0.02 }),
];

describe("useLeaderboardColumns dedups a key folded into both params and metrics", () => {
  it("shows the shared key once, categorized as a param", () => {
    const { result } = renderHook(() =>
      useLeaderboardColumns(ROWS, null, new Set(), "/ws/test/app/my-app", null));
    expect(result.current.metricCols).toEqual(["loss"]);
    expect(result.current.paramCols).toEqual(["lr"]);
    expect(result.current.visibleMetrics).toEqual(["loss"]);
    expect(result.current.visibleParams).toEqual(["lr"]);
  });

  it("never lists the same key in both the metric and param column sets", () => {
    const { result } = renderHook(() =>
      useLeaderboardColumns(ROWS, null, new Set(), "/ws/test/app/my-app", null));
    const overlap = result.current.metricCols.filter((c) => result.current.paramCols.includes(c));
    expect(overlap).toEqual([]);
  });
});
