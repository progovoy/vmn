/** Plan 32 F1: a metric value names the summary policy its run's own
 *  `define_metric` picked unlike the schema (the server's `metric_policy`
 *  lists only those overrides). */
import { describe, it, expect } from "vitest";
import { mixText, mixedPolicies, policyTag } from "../metricPolicy";
import type { ExperimentRow } from "../../types";

const row = (metrics: ExperimentRow["metrics"], metric_policy?: ExperimentRow["metric_policy"]) =>
  ({ idx: 1, verstr: "v", code_verstr: "v", timestamp: null, note: null, branch: null,
     base_version: null, metrics, metric_policy }) as ExperimentRow;

describe("a cell's policy tag", () => {
  it("names its run's override", () => {
    expect(policyTag(row({ loss: 0.2 }, { loss: "min" }), "loss")).toBe("min");
    expect(policyTag(row({ loss: 0.9 }, { loss: "last" }), "loss")).toBe("last");
  });

  it("is null when the run follows the schema or has no value", () => {
    expect(policyTag(row({ loss: 0.9 }), "loss")).toBeNull();
    expect(policyTag(row({}, { loss: "min" }), "loss")).toBeNull();
  });
});

describe("a column of loaded rows", () => {
  it("is mixed when a row carrying the metric overrides the schema", () => {
    expect(mixedPolicies([row({ loss: 0.2 }, { loss: "min" }), row({ loss: 0.9 })], "loss")).toBe(true);
    expect(mixedPolicies([row({ loss: 0.2 }, { acc: "max" }), row({ loss: 0.9 })], "loss")).toBe(false);
    expect(mixedPolicies([row({ loss: 0.2 }), row({ loss: 0.9 })], "loss")).toBe(false);
  });
});

describe("an aggregate over overrides", () => {
  it("says how many runs use each override", () => {
    expect(mixText({ min: 3 })).toBe("3 runs use min");
    expect(mixText({ last: 1, max: 2 })).toBe("1 run uses last, 2 runs use max");
  });

  it("is null without one", () => {
    expect(mixText(undefined)).toBeNull();
    expect(mixText({})).toBeNull();
  });
});
