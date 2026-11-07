import { describe, it, expect } from "vitest";
import { isFoldedParam, isParamOnly } from "../paramKeys";
import type { ExperimentDetail } from "../../types";

/** Plan 32 F8: a metric is a param's fold only when the run never logged
 *  it — `logged_params` names the params it also logged, whether once or
 *  many times (a once-logged metric has no `metric_summary` entry). */
describe("isFoldedParam", () => {
  it("is a param the run never logged as a metric", () => {
    expect(isFoldedParam({ params: { lr: 0.01 } }, "lr")).toBe(true);
  });

  it("is not a param the run also logged", () => {
    expect(isFoldedParam({ params: { acc: 3 }, logged_params: ["acc"] }, "acc")).toBe(false);
  });

  it("is not a name outside params", () => {
    expect(isFoldedParam({ params: {} }, "loss")).toBe(false);
  });
});

describe("isParamOnly on a run detail", () => {
  it("keeps a once-logged metric sharing a param's name a metric", () => {
    const d: ExperimentDetail = {
      metadata: { verstr: "0.0.1-dev.x" }, params: { acc: 3 }, metrics: { acc: 0.9 },
      metric_summary: {}, logged_params: ["acc"], series: {}, patches: {},
    };
    expect(isParamOnly("acc", d)).toBe(false);
  });
});
