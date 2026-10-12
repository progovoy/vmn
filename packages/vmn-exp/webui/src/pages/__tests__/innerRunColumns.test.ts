import { describe, it, expect } from "vitest";
import { headGroups, INNER_RUN_COLS, innerRunCount } from "../innerRunColumns";
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
