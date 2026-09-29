import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import { schemaHides } from "../../util/hiddenMetrics";
import type { ExperimentRow, MetricsSchema } from "../../types";

const row = (metrics: Record<string, number>): ExperimentRow => ({
  idx: 1, verstr: "0.0.1", code_verstr: "0.0.1", timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params: {}, metrics,
});

const ROWS = [row({ loss: 0.5, grad_norm: 1, grad_max: 2, lr: 0.1 })];

describe("schema-hidden metric columns", () => {
  it("are offered but not shown by default", () => {
    const schema: MetricsSchema = { lr: { hidden: true }, "grad_*": { hidden: true } };
    const { result } = renderHook(() =>
      useLeaderboardColumns(ROWS, schema, new Set<string>(), "", null));
    expect([...result.current.metricCols].sort()).toEqual(["grad_max", "grad_norm", "loss", "lr"]);
    expect(result.current.visibleMetrics).toEqual(["loss"]);
  });

  it("show once toggled, like any other column", () => {
    const schema: MetricsSchema = { lr: { hidden: true } };
    const toggled = new Set(["m:lr", "m:loss"]);
    const { result } = renderHook(() => useLeaderboardColumns(ROWS, schema, toggled, "", null));
    expect([...result.current.visibleMetrics].sort()).toEqual(["grad_max", "grad_norm", "lr"]);
  });
});

describe("schemaHides", () => {
  it("prefers the exact name over a glob", () => {
    const schema: MetricsSchema = { "grad_*": { hidden: true }, grad_norm: { hidden: false } };
    expect(schemaHides(schema, "grad_norm")).toBe(false);
    expect(schemaHides(schema, "grad_max")).toBe(true);
    expect(schemaHides(schema, "loss")).toBe(false);
    expect(schemaHides(null, "loss")).toBe(false);
  });

  it("matches fnmatch ? and [] and treats other characters literally", () => {
    const schema: MetricsSchema = { "val.?": { hidden: true }, "l[ro]ss": { hidden: true } };
    expect(schemaHides(schema, "val.a")).toBe(true);
    expect(schemaHides(schema, "valxa")).toBe(false);
    expect(schemaHides(schema, "loss")).toBe(true);
  });
});
