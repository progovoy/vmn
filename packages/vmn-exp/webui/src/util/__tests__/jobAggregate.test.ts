/** Plan 31 §2: the Outer runs row's chosen aggregate (`rolled`) as the web
 *  names it — the header, the cell title (source and coverage, plan 32)
 *  and the URL's `job_agg*` values. */
import { describe, it, expect } from "vitest";
import {
  coverageText, parseJobAgg, rolledHeader, rolledLabel, rolledTitle, tailLabel, unitNouns,
} from "../jobAggregate";
import { rolled } from "./jobFixture";

const DATES = { by: "field:params.trade_date", source: "own" as const, metric: "date.best_value" };

describe("the units an aggregate is over", () => {
  it("names children, runs, a field's and a kind's units", () => {
    expect(unitNouns("children")).toEqual({ one: "child", many: "children" });
    expect(unitNouns("runs")).toEqual({ one: "run", many: "runs" });
    expect(unitNouns("field:params.trade_date")).toEqual({ one: "date", many: "dates" });
    expect(unitNouns("field:tags.fold")).toEqual({ one: "fold", many: "folds" });
    expect(unitNouns("kind:date")).toEqual({ one: "date", many: "dates" });
  });
});

describe("a tail's label", () => {
  it("names the percentile the goal points at, flipped for lower-is-better", () => {
    expect(tailLabel("best10", "max")).toBe("best10 (p90)");
    expect(tailLabel("worst10", "max")).toBe("worst10 (p10)");
    expect(tailLabel("best10", "min")).toBe("best10 (p10)");
    expect(tailLabel("worst10", "min")).toBe("worst10 (p90)");
  });

  it("names no percentile without a goal, and leaves the rest as they are", () => {
    expect(tailLabel("best10", null)).toBe("best10");
    expect(tailLabel("median", "max")).toBe("median");
  });
});

describe("the value column's header", () => {
  it("reads the aggregate and its units", () => {
    expect(rolledHeader(rolled({ agg: "median", ...DATES }))).toBe("median · dates");
    expect(rolledHeader(rolled({ agg: "best10", percentile: "p90", ...DATES }))).toBe("best10 (p90) · dates");
    expect(rolledHeader(rolled())).toBe("best · children");
  });
});

describe("a value cell's title", () => {
  it("names the aggregate, the coverage, the units and the source", () => {
    expect(rolledTitle(rolled({ agg: "median", ...DATES, n: 14, of: 16 })))
      .toBe("median of 14/16 dates' own date.best_value");
    expect(rolledTitle(rolled({ agg: "median", n: 16, of: 16 })))
      .toBe("median of 16 children's best val_loss");
  });

  it("names a tail's percentile", () => {
    expect(rolledTitle(rolled({ agg: "best10", percentile: "p90", ...DATES, n: 16, of: 16 })))
      .toBe("best10 (p90) of 16 dates' own date.best_value");
  });

  it("counts the duplicate field values left out", () => {
    expect(rolledTitle(rolled({ agg: "median", ...DATES, n: 15, of: 16, conflicts: 1 })))
      .toBe("median of 15/16 dates' own date.best_value · 1 duplicate date left out");
    expect(rolledTitle(rolled({ agg: "median", ...DATES, n: 14, of: 16, conflicts: 2 })))
      .toBe("median of 14/16 dates' own date.best_value · 2 duplicate dates left out");
  });

  it("marks an approximate quantile over every run", () => {
    expect(rolledTitle(rolled({ agg: "median", by: "runs", n: 16_384, of: 16_400, approx: true })))
      .toBe("≈ median of 16,384/16,400 runs' val_loss");
  });

  it("says a goal-less metric is not ranked", () => {
    expect(rolledTitle(rolled({ agg: "median", goal: null, value: null })))
      .toBe("no goal declared for val_loss — not ranked");
  });
});

describe("an aggregate's label and coverage (KPI tile, baseline card)", () => {
  it("names the aggregate, the metric and the units", () => {
    expect(rolledLabel(rolled({ agg: "median", ...DATES }))).toBe("median date.best_value · dates");
    expect(rolledLabel(rolled({ agg: "worst10", percentile: "p10", ...DATES }))).toBe("worst10 (p10) date.best_value · dates");
  });

  it("reads the coverage with its source", () => {
    expect(coverageText(rolled({ agg: "median", ...DATES, n: 14, of: 16 }))).toBe("of 14/16 dates' own");
    expect(coverageText(rolled({ agg: "median", by: "runs", n: 9, of: 9 }))).toBe("of 9 runs");
  });
});

describe("the URL's job_agg values", () => {
  const parse = (q: string) => parseJobAgg(new URLSearchParams(q));

  it("reads each one the server takes, null when absent", () => {
    expect(parse("job_agg=median&job_agg_by=field:params.trade_date&job_agg_value=own&job_agg_metric=date.best_value"))
      .toEqual({ agg: "median", by: "field:params.trade_date", value: "own", metric: "date.best_value" });
    expect(parse("")).toEqual({ agg: null, by: null, value: null, metric: null });
    expect(parse("job_agg=worst10&job_agg_by=kind:date").agg).toBe("worst10");
    expect(parse("job_agg_by=runs").by).toBe("runs");
    expect(parse("job_agg_by=kind:date").by).toBe("kind:date");
  });

  it("drops a value the server would refuse", () => {
    expect(parse("job_agg=p90&job_agg_by=depth:2&job_agg_value=last&job_agg_by=field:name"))
      .toEqual({ agg: null, by: null, value: null, metric: null });
    expect(parse("job_agg_by=field:name").by).toBeNull();
  });
});
