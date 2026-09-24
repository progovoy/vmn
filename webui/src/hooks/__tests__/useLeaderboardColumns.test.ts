import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import type { ExperimentFacets, ExperimentRow } from "../../types";

function row(i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx: i,
    verstr: `0.0.${i}`,
    code_verstr: `0.0.${i}`,
    timestamp: null,
    note: null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    params: {},
    metrics: {},
    ...extra,
  };
}

const hidden = new Set<string>();

describe("useLeaderboardColumns facets", () => {
  it("offers metric/param columns from facets even when no loaded row carries them", () => {
    const rows = [row(1, { metrics: { loss: 0.5 }, params: { lr: 0.1 } })];
    const facets: ExperimentFacets = {
      branches: [],
      metric_keys: ["loss", "accuracy"],
      param_keys: ["lr", "batch_size"],
      total: 500,
    };
    const { result } = renderHook(() => useLeaderboardColumns(rows, null, hidden, "", facets));
    expect(result.current.metricCols).toEqual(["accuracy", "loss"]);
    expect(result.current.paramCols).toEqual(["batch_size", "lr"]);
  });

  it("falls back to what the loaded rows carry when there are no facets", () => {
    const rows = [row(1, { metrics: { loss: 0.5 }, params: { lr: 0.1 } })];
    const { result } = renderHook(() => useLeaderboardColumns(rows, null, hidden, "", null));
    expect(result.current.metricCols).toEqual(["loss"]);
    expect(result.current.paramCols).toEqual(["lr"]);
  });

  it("keeps a schema-primary metric first even when facets add more columns", () => {
    const rows = [row(1, { metrics: { loss: 0.5 } })];
    const facets: ExperimentFacets = {
      branches: [], metric_keys: ["loss", "accuracy"], param_keys: [], total: 10,
    };
    const schema = { loss: { primary: true } };
    const { result } = renderHook(() => useLeaderboardColumns(rows, schema, hidden, "", facets));
    expect(result.current.metricCols).toEqual(["loss", "accuracy"]);
  });
});
