/** Plan 31 §2: the Outer runs row's aggregate travels as `job_agg`,
 *  `job_agg_by`, `job_agg_value`, `job_agg_metric`, each left out when unset. */
import { describe, it, expect } from "vitest";
import { setFilter } from "../api";

const query = (opts: Parameters<typeof setFilter>[1]) => {
  const p = new URLSearchParams();
  setFilter(p, opts);
  return Object.fromEntries(p);
};

describe("the job_agg request params", () => {
  it("names each one given", () => {
    expect(query({
      top: true, jobAgg: "median", jobAggBy: "field:params.trade_date", jobAggValue: "own", jobAggMetric: "date.best_value",
    })).toEqual({
      top: "1", job_agg: "median", job_agg_by: "field:params.trade_date", job_agg_value: "own", job_agg_metric: "date.best_value",
    });
  });

  it("leaves out the ones not given: the app's default", () => {
    expect(query({ top: true, jobAgg: "max" })).toEqual({ top: "1", job_agg: "max" });
  });
});

describe("job_agg_nested (plan 35 §2)", () => {
  it("travels as 1 or 0, left out when unset", () => {
    expect(query({ top: true, jobAggNested: true })).toEqual({ top: "1", job_agg_nested: "1" });
    expect(query({ top: true, jobAggNested: false })).toEqual({ top: "1", job_agg_nested: "0" });
    expect(query({ top: true })).toEqual({ top: "1" });
  });
});
