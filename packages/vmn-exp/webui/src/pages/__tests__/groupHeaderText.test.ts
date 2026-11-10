import { describe, it, expect } from "vitest";
import { aggregateCell, barSegments, countParts, countsText, jobGroupCell, sizeText, spokenCounts } from "../groupHeaderText";
import { rolled } from "../../util/__tests__/jobFixture";

const counts = (extra = {}) => ({ total: 16, running: 2, waiting: 0, done: 13, failed: 1, stuck: 0, ...extra });
const agg = (extra = {}) => ({ mean: 0.5, best: 0.2, median: 0.4, min: 0.2, max: 0.9, n: 16, goal: "min" as const, ...extra });

describe("a group header's status count (plan 22 G4)", () => {
  it("reads the total in words, then every state that is not done (F2)", () => {
    expect(countsText(counts())).toBe("16 runs · 2 running · 1 failed");
    expect(countsText(counts({ running: 0, failed: 0, waiting: 3, stuck: 1 }))).toBe("16 runs · 3 waiting · 1 stuck");
    expect(countsText(counts({ total: 1, running: 1, failed: 0, done: 0 }))).toBe("1 run · 1 running");
  });

  it("says a group whose runs all succeeded is all succeeded (F2)", () => {
    expect(countsText(counts({ total: 4, running: 0, failed: 0, done: 4 }))).toBe("4 runs · all succeeded");
    expect(countParts(counts({ total: 4, running: 0, failed: 0, done: 4 })).map((p) => p.tone)).toEqual(["total", "done"]);
  });

  it("reads `5 of 16` when the filters leave part of the group (F1)", () => {
    expect(countsText(counts({ total: 5 }), 16)).toBe("5 of 16 runs · 2 running · 1 failed");
    expect(countsText(counts({ total: 1, running: 0, failed: 0, done: 1 }), 3)).toBe("1 of 3 runs · 1 succeeded");
    // No filter (or a server without the field): the plain count.
    expect(countsText(counts(), 16)).toBe("16 runs · 2 running · 1 failed");
    expect(countsText(counts(), undefined)).toBe("16 runs · 2 running · 1 failed");
  });

  it("never says `all succeeded` of a group the filters cut, it names the count", () => {
    const ok = counts({ total: 5, running: 0, failed: 0, done: 5 });
    expect(countsText(ok, 16)).toBe("5 of 16 runs · 5 succeeded");
    expect(countParts(ok, 16).map((p) => p.tone)).toEqual(["total", "done"]);
    expect(spokenCounts(ok, 16)).toBe("5 of 16 runs, 5 succeeded");
    // Unfiltered keeps the short wording.
    expect(countsText(counts({ running: 0, failed: 0, done: 16 }), 16)).toBe("16 runs · all succeeded");
  });

  it("reads only the size for a header whose counts sit in columns (F10)", () => {
    expect(sizeText(counts())).toBe("16 runs");
    expect(sizeText(counts({ total: 1 }))).toBe("1 run");
    expect(sizeText(counts({ total: 5 }), 16)).toBe("5 of 16 runs");
    expect(sizeText(counts(), 16)).toBe("16 runs");
  });

  it("tags each part with its state, so it can be coloured", () => {
    expect(countParts(counts()).map((p) => p.tone)).toEqual(["total", "running", "failed"]);
  });

  it("says the counts in words for a screen reader", () => {
    expect(spokenCounts(counts())).toBe("16 runs, 2 running, 1 failed");
    expect(spokenCounts(counts({ total: 1, running: 0, failed: 0 }))).toBe("1 run, all succeeded");
    expect(spokenCounts(counts({ total: 5 }), 16)).toBe("5 of 16 runs, 2 running, 1 failed");
  });
});

describe("a group header's aggregate cell (plan 22 G10)", () => {
  it("shows the chosen aggregate and names it with its count", () => {
    expect(aggregateCell(agg(), "mean")).toEqual({ value: 0.5, title: "mean of 16" });
    expect(aggregateCell(agg(), "median")).toEqual({ value: 0.4, title: "median of 16" });
    expect(aggregateCell(agg(), "best")).toEqual({ value: 0.2, title: "best of 16" });
  });

  it("has no best for a metric without a goal, and says so, never the mean (plan 32 F6)", () => {
    expect(aggregateCell(agg({ best: null, goal: null }), "best")).toEqual({ value: null, title: "best of 16 (no goal)" });
  });

  it("reads (no goal) from the aggregate's goal, never from a null best (plan 32)", () => {
    expect(aggregateCell(agg({ best: null }), "best").title).toBe("best of 16");
    expect(aggregateCell(agg({ goal: null }), "mean").title).toBe("mean of 16");
  });

  it("names a tail's percentile by the goal, and has none without a goal (plan 31 §2)", () => {
    const tails = agg({ best10: 0.25, worst10: 0.8 });
    expect(aggregateCell(tails, "best10")).toEqual({ value: 0.25, title: "best10 (p10) of 16" });
    expect(aggregateCell(agg({ best10: 0.85, goal: "max" }), "best10")).toEqual({ value: 0.85, title: "best10 (p90) of 16" });
    expect(aggregateCell(agg({ worst10: null, goal: null }), "worst10")).toEqual({ value: null, title: "worst10 of 16 (no goal)" });
  });

  it("is empty when the group has no value of the metric", () => {
    expect(aggregateCell(undefined, "mean")).toEqual({ value: null, title: undefined });
    expect(aggregateCell(agg({ mean: null, n: 0 }), "mean")).toEqual({ value: null, title: undefined });
  });
});

describe("a big group's count (plan 23)", () => {
  it("groups the thousands of every number it names", () => {
    const big = counts({ total: 4000, running: 1200, done: 1500, failed: 1300 });
    expect(countsText(big)).toBe("4,000 runs · 1,200 running · 1,300 failed");
    expect(countsText(counts({ total: 2500, running: 0, failed: 0, done: 2500 }), 4000)).toBe("2,500 of 4,000 runs · 2,500 succeeded");
  });
});

describe("a group header's run bar (plan 22 F13)", () => {
  it("fills from the left with the finished runs, then the running; waiting runs are the empty track", () => {
    expect(barSegments(counts())).toEqual([
      { tone: "done", pct: 81.25 }, { tone: "failed", pct: 6.25 }, { tone: "running", pct: 12.5 },
    ]);
    expect(barSegments(counts({ total: 3, running: 0, done: 1, failed: 0, stuck: 1, waiting: 1 }))).toEqual([
      { tone: "done", pct: 33.33 }, { tone: "stuck", pct: 33.33 },
    ]);
  });

  it("is an empty track while every run waits, and absent for a group of one run", () => {
    expect(barSegments(counts({ total: 3, running: 0, done: 0, failed: 0, waiting: 3 }))).toEqual([]);
    expect(barSegments(counts({ total: 1, running: 0, done: 1, failed: 0 }))).toBeNull();
    expect(barSegments(counts({ total: 0, running: 0, done: 0, failed: 0 }))).toBeNull();
  });
});

describe("a grouped Outer runs header's value (plan 34 §1, plan 32)", () => {
  const DATES = rolled({ agg: "median", by: "field:params.trade_date", source: "own", metric: "date.best_value", goal: "max" });
  // The group's attempts' units pooled: the rows' aggregate, from_earlier beside it.
  const pooled = (extra = {}) => ({ ...agg({ median: 0.65, goal: "max" as const }), ...DATES,
    value: 0.65, n: 14, of: 16, from_earlier: 3, ...extra });

  it("names the rows' aggregate of the pooled units and the ones from earlier attempts", () => {
    expect(jobGroupCell(pooled(), DATES)).toEqual({
      name: "median", value: "0.65", coverage: "14/16", noGoal: false, mix: null,
      title: "median of 14/16 dates' own date.best_value · 3 from earlier attempts",
    });
    expect(jobGroupCell(pooled({ n: 16, from_earlier: 0 }), DATES).title).toBe("median of 16 dates' own date.best_value");
    expect(jobGroupCell(pooled({ from_earlier: 1 }), DATES).title).toBe("median of 14/16 dates' own date.best_value · 1 from an earlier attempt");
    const runs = rolled({ by: "runs", agg: "median" });
    expect(jobGroupCell(pooled({ ...runs, value: 0.4, n: 9, of: 9, approx: true, from_earlier: 0 }), runs))
      .toMatchObject({ value: "≈ 0.4", coverage: "9", title: "≈ median of 9 runs' val_loss" });
  });

  it("names a tail's percentile", () => {
    const tails = rolled({ ...DATES, agg: "best10", percentile: "p90" });
    const cell = jobGroupCell(pooled({ ...tails, value: 0.8, n: 14, of: 16 }), tails);
    expect(cell.name).toBe("best10 (p90)");
    expect(cell.value).toBe("0.8");
    expect(cell.title).toBe("best10 (p90) of 14/16 dates' own date.best_value · 3 from earlier attempts");
  });

  it("reads `— (no goal)` without a goal, never a value", () => {
    const noGoal = rolled({ ...DATES, goal: null, value: null });
    expect(jobGroupCell(undefined, noGoal)).toEqual({
      name: null, value: "—", coverage: null, noGoal: true, mix: null,
      title: "no goal declared for date.best_value — not ranked",
    });
  });

  it("reads `—` when no unit of the group's outer runs has a value", () => {
    const none = { name: null, value: "—", coverage: null, noGoal: false, mix: null, title: "no outer run of the group has a date.best_value" };
    expect(jobGroupCell(undefined, DATES)).toEqual(none);
    expect(jobGroupCell(pooled({ n: 0, value: null }), DATES)).toEqual(none);
  });

  it("marks the runs overriding the schema's summary policy", () => {
    const cell = jobGroupCell(pooled({ mixed: true, policies: { min: 3 } }), DATES);
    expect(cell.mix).toBe("3 runs use min");
    expect(cell.title).toBe("median of 14/16 dates' own date.best_value · 3 from earlier attempts · 3 runs use min");
  });
});
