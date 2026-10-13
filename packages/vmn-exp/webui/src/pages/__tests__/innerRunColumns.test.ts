import { describe, it, expect } from "vitest";
import { countVisible, headGroups, INNER_RUN_COLS, innerRunCount, innerTotal } from "../innerRunColumns";
import type { ExperimentRow } from "../../types";

describe("the Inner runs header group", () => {
  it("names the five inner-run count columns", () => {
    expect(INNER_RUN_COLS).toEqual(["total", "waiting", "running", "done", "failed"]);
  });

  it("spans the contiguous count block and leaves every other column its own cell", () => {
    const ids = ["check", "idx", "status", "experiment", "c:total", "c:waiting", "c:running", "c:done",
      "c:failed", "c:started", "m:loss", "note", "when"];
    expect(headGroups(ids)).toEqual([
      { start: 0, span: 1, inner: false }, { start: 1, span: 1, inner: false },
      { start: 2, span: 1, inner: false }, { start: 3, span: 1, inner: false },
      { start: 4, span: 5, inner: true },
      { start: 9, span: 1, inner: false }, { start: 10, span: 1, inner: false },
      { start: 11, span: 1, inner: false }, { start: 12, span: 1, inner: false },
    ]);
  });

  it("labels each block again when a count column is dragged away from the rest", () => {
    const ids = ["experiment", "c:total", "c:waiting", "m:loss", "c:failed"];
    expect(headGroups(ids)!.filter((g) => g.inner)).toEqual([
      { start: 1, span: 2, inner: true }, { start: 4, span: 1, inner: true },
    ]);
  });

  it("gives a windowed table's gap column a cell of its own", () => {
    const ids = ["experiment", "gap:left", "c:total", "c:waiting", "gap:right"];
    expect(headGroups(ids)).toEqual([
      { start: 0, span: 1, inner: false }, { start: 1, span: 1, inner: false },
      { start: 2, span: 2, inner: true }, { start: 4, span: 1, inner: false },
    ]);
  });

  it("has no group without count columns", () => {
    expect(headGroups(["experiment", "c:started", "m:loss"])).toBeNull();
  });
});

describe("an inner-run count cell", () => {
  const outer = {
    kind: "outer", children: ["a", "b", "c"], child_counts: { created: 1, running: 1, failed: 1 },
  } as unknown as ExperimentRow;
  const single = { kind: "single", children: [] } as unknown as ExperimentRow;

  it("counts an outer run's inner runs, zeros included", () => {
    expect(innerRunCount(outer, "total")).toBe("3");
    expect(innerRunCount(outer, "done")).toBe("0");
    expect(innerRunCount(outer, "failed")).toBe("1");
  });

  it("is empty for a run without inner runs, never a dash or a zero", () => {
    for (const c of INNER_RUN_COLS) expect(innerRunCount(single, c)).toBe("");
  });
});

describe("the total cell of an incomplete sweep (plan 20 A7)", () => {
  const sweep = (trials: number) => ({
    kind: "outer", status: "created", tree_status: trials < 20 ? "created" : "succeeded",
    children: Array.from({ length: trials }, (_, i) => `k${i}`), child_counts: { succeeded: trials },
    sweep_planned: 20, sweep_trials: trials,
  }) as unknown as ExperimentRow;

  it("reads 16/20 · incomplete, with a sentence for screen readers", () => {
    expect(innerTotal(sweep(16))).toEqual({
      text: "16/20 · incomplete", label: "16 inner runs, 16 of 20 planned trials, incomplete",
    });
  });

  it("is null for a complete sweep, so the cell shows its count", () => {
    expect(innerTotal(sweep(20))).toBeNull();
  });
});

describe("whether a count column shows", () => {
  const none = new Set<string>();
  const set = (...keys: string[]) => new Set(keys);

  it("shows while an outer run is loaded, else not", () => {
    expect(countVisible("c:running", none, none, true)).toBe(true);
    expect(countVisible("c:running", none, none, false)).toBe(false);
  });

  it("lets its own show=/hide= win", () => {
    expect(countVisible("c:done", set("c:done"), none, false)).toBe(true);
    expect(countVisible("c:done", none, set("c:done"), true)).toBe(false);
    expect(countVisible("c:done", set("c:done"), set("c:inner"), true)).toBe(true);
    expect(countVisible("c:done", set("c:inner"), set("c:done"), true)).toBe(false);
  });

  it("reads the single inner column's c:inner as all five", () => {
    for (const c of INNER_RUN_COLS) {
      expect(countVisible(`c:${c}`, set("c:inner"), new Set<string>(), false)).toBe(true);
      expect(countVisible(`c:${c}`, new Set<string>(), set("c:inner"), true)).toBe(false);
    }
  });
});
