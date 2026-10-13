import { describe, it, expect } from "vitest";
import { INNER_COLUMN, innerRunSummary } from "../innerRunColumns";
import type { ExperimentRow } from "../../types";

const outer = (counts: Record<string, number>, children = 5, expected?: number) => ({
  kind: "outer", children: Array.from({ length: children }, (_, i) => `c${i}`), child_counts: counts,
  ...(expected ? { fleet: { expected } } : {}),
}) as unknown as ExperimentRow;

describe("the inner column (C2)", () => {
  it("is one column", () => {
    expect(INNER_COLUMN).toBe("c:inner");
  });

  it("reads total · running · failed, leaving out the states with no runs", () => {
    const s = innerRunSummary(outer({ running: 4, failed: 1 }))!;
    expect(s.text).toBe("5 · 4 running · 1 failed");
    expect(s.parts.map((p) => p.state)).toEqual(["running", "failed"]);
  });

  it("tells screen readers what the numbers count", () => {
    expect(innerRunSummary(outer({ running: 4, failed: 1 }))!.label).toBe("5 inner runs, 4 running, 1 failed");
    expect(innerRunSummary(outer({ succeeded: 1 }, 1))!.label).toBe("1 inner run, 1 done");
  });

  it("counts stuck runs as failed and created ones as waiting", () => {
    const s = innerRunSummary(outer({ stuck: 1, failed: 1, created: 2, succeeded: 1 }))!;
    expect(s.text).toBe("5 · 2 failed · 2 waiting · 1 done");
  });

  it("totals a fleet's planned size, not only the runs it has so far", () => {
    expect(innerRunSummary(outer({ running: 2 }, 2, 8))!.text).toBe("8 · 2 running");
  });

  it("is empty for a run without inner runs", () => {
    expect(innerRunSummary({ kind: "single", children: [] } as unknown as ExperimentRow)).toBeNull();
  });
});
