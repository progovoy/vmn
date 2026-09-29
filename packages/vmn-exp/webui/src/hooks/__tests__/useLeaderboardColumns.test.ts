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
   
    params: {},
    metrics: {},
    ...extra,
  };
}

const hidden = new Set<string>();
const noOrder: readonly string[] = [];

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

describe("useLeaderboardColumns order and pinning", () => {
  it("cells follow col= order: acc before loss when col=m:acc&col=m:loss", () => {
    const rows = [row(1, { metrics: { loss: 0.5, acc: 0.9 } })];
    const order = ["m:acc", "m:loss"];
    const { result } = renderHook(() =>
      useLeaderboardColumns(rows, null, hidden, "", null, order, noOrder));
    expect(result.current.cells[0]).toEqual({ kind: "metric", key: "acc" });
    expect(result.current.cells[1]).toEqual({ kind: "metric", key: "loss" });
  });

  it("pinned cells come before unpinned within the combined list", () => {
    const rows = [row(1, { metrics: { loss: 0.5, acc: 0.9 }, params: { lr: 0.1 } })];
    const pinned = ["m:acc"];
    const { result } = renderHook(() =>
      useLeaderboardColumns(rows, null, hidden, "", null, noOrder, pinned));
    expect(result.current.cells[0]).toEqual({ kind: "metric", key: "acc" });
  });

  it("styles are referentially stable across equal rerenders", () => {
    const rows = [row(1, { metrics: { loss: 0.5 }, params: { lr: 0.1 } })];
    const { result, rerender } = renderHook(() =>
      useLeaderboardColumns(rows, null, hidden, "", null));
    const styles1 = result.current.layout.styles;
    rerender();
    expect(result.current.layout.styles).toBe(styles1);
  });

  it("old call (no order/pin) renders default order unchanged", () => {
    const rows = [row(1, { metrics: { loss: 0.5, acc: 0.9 } })];
    const { result } = renderHook(() =>
      useLeaderboardColumns(rows, null, hidden, "", null));
    // default: schema/facet order, then alpha — loss and acc are both extras so alpha: acc, loss
    expect(result.current.metricCols).toEqual(["acc", "loss"]);
  });
});
