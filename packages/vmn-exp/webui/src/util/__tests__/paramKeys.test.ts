import { describe, it, expect } from "vitest";
import { isParamOnly } from "../paramKeys";
import type { ExperimentDetail } from "../../types";

/** Build a detail with specified params, metrics and optional metric_summary. */
function makeDetail(opts: {
  params?: Record<string, unknown>;
  metrics?: ExperimentDetail["metrics"];
  metric_summary?: Record<string, { last: number | null; min: number | null; max: number | null }>;
}): ExperimentDetail {
  return {
    metadata: { verstr: "0.0.1-dev.x" },
    params: opts.params ?? {},
    metrics: opts.metrics ?? {},
    metric_summary: opts.metric_summary,
    series: {},
    patches: {},
  };
}

describe("isParamOnly", () => {
  it("returns true for a key in params but with no metric_summary entry", () => {
    const d = makeDetail({
      params: { lr: 0.001, batch_size: 32 },
      metrics: { lr: 0.001, loss: 0.5 },
      metric_summary: { loss: { last: 0.5, min: 0.3, max: 0.8 } },
    });
    expect(isParamOnly("lr", d)).toBe(true);
    expect(isParamOnly("batch_size", d)).toBe(true);
  });

  it("returns false for a metric with a metric_summary entry (logged >1 time)", () => {
    const d = makeDetail({
      params: {},
      metrics: { loss: 0.5 },
      metric_summary: { loss: { last: 0.5, min: 0.3, max: 0.8 } },
    });
    expect(isParamOnly("loss", d)).toBe(false);
  });

  it("returns false for a key not in params at all", () => {
    const d = makeDetail({
      params: {},
      metrics: { acc: 0.9 },
      metric_summary: {},
    });
    expect(isParamOnly("acc", d)).toBe(false);
  });

  it("returns true even when metric_summary is undefined (older servers)", () => {
    const d = makeDetail({
      params: { seed: 42 },
      metrics: { seed: 42, loss: 0.3 },
    });
    // Without metric_summary, a key in params is param-only
    expect(isParamOnly("seed", d)).toBe(true);
  });

  it("returns false when the key has a metric_summary even though it is also in params", () => {
    // A numeric param that was also logged as a metric (rare but possible)
    const d = makeDetail({
      params: { lr: 0.001 },
      metrics: { lr: 0.001 },
      metric_summary: { lr: { last: 0.001, min: 0.001, max: 0.001 } },
    });
    expect(isParamOnly("lr", d)).toBe(false);
  });
});
