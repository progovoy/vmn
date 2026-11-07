import { describe, it, expect } from "vitest";
import { metricColumns, paramKey } from "../leaderboardColumns";
import type { ExperimentRow } from "../../types";

/** Plan 32 F8: a param never takes a logged metric's place; the row's
 *  `logged_params` names the params it also logged as metrics, so a metric
 *  column is kept by the logged metric, not dropped by the shared name. */
function row(
  metrics: Record<string, number>,
  params: Record<string, unknown>,
  logged?: string[],
): ExperimentRow {
  return {
    idx: 1, verstr: "v1", code_verstr: "v1", timestamp: null, note: null,
    branch: "main", base_version: "0.0.1", params, metrics,
    ...(logged ? { logged_params: logged } : {}),
  };
}

describe("metricColumns keys on the logged metric", () => {
  it("keeps a logged metric that shares a param's name", () => {
    const rows = [row({ acc: 0.9 }, { acc: 3 }, ["acc"])];
    expect(metricColumns(rows, null)).toEqual(["acc"]);
    expect(paramKey(rows)).toBe("acc");
  });

  it("keeps it when another row has the name only as a param", () => {
    const rows = [row({ acc: 3 }, { acc: 3 }), row({ acc: 0.9 }, { acc: 4 }, ["acc"])];
    expect(metricColumns(rows, { acc: { goal: "max" } })).toEqual(["acc"]);
  });

  it("still drops a name every row has only as a param", () => {
    const rows = [row({ lr: 0.01, acc: 0.9 }, { lr: 0.01, acc: 3 }, ["acc"])];
    expect(metricColumns(rows, null)).toEqual(["acc"]);
  });
});
