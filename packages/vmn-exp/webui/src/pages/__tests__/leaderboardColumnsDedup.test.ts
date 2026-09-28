import { describe, it, expect } from "vitest";
import { metricColumns, paramKey } from "../leaderboardColumns";
import type { ExperimentRow } from "../../types";

/** A numeric param folds into `metrics` too (server-side, intentional — see
 *  CLAUDE.md), so a row can carry the same key in both `params` and
 *  `metrics`. The column-building logic must show it once, as a param. */
function row(
  metrics: Record<string, number>,
  params: Record<string, unknown>,
): ExperimentRow {
  return {
    idx: 1, verstr: "v1", code_verstr: "v1", timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", user_meta: null, params, metrics,
  };
}

describe("metricColumns excludes keys that also appear as params", () => {
  it("drops a key present in both params and metrics with the same value", () => {
    const rows = [
      row({ loss: 0.5, lr: 0.01 }, { lr: 0.01 }),
      row({ loss: 0.3, lr: 0.02 }, { lr: 0.02 }),
    ];
    expect(metricColumns(rows, null)).toEqual(["loss"]);
    expect(paramKey(rows)).toBe("lr");
  });

  it("drops a key present in both even when the folded value differs", () => {
    const rows = [row({ lr: 999 }, { lr: 0.01 })];
    expect(metricColumns(rows, null)).toEqual([]);
    expect(paramKey(rows)).toBe("lr");
  });

  it("keeps a schema-listed metric that also folds from a param", () => {
    const rows = [row({ lr: 0.01 }, { lr: 0.01 })];
    expect(metricColumns(rows, { lr: { goal: "min" } })).toEqual([]);
  });

  it("still lists a metric with no matching param", () => {
    const rows = [row({ loss: 0.5 }, {})];
    expect(metricColumns(rows, null)).toEqual(["loss"]);
  });
});
