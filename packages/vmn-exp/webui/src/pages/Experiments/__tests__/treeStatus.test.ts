import { describe, expect, it } from "vitest";
import { treeStatusQuery } from "../treeStatus";

describe("the outer runs' status chips", () => {
  // A launch run ends once it has submitted its tree: its own status and its
  // tree_status (a failed run anywhere reads failed) say nothing of the runs
  // still running below it.
  it("match running and stuck anywhere in the tree", () => {
    expect(treeStatusQuery("running")).toBe('status = "running" or running_below > 0');
    expect(treeStatusQuery("stuck")).toBe('status = "stuck" or stuck_below > 0');
  });

  it("match the ended states by the tree's rollup", () => {
    expect(treeStatusQuery("failed")).toBe('tree_status = "failed"');
    expect(treeStatusQuery("succeeded,created")).toBe('tree_status = "succeeded" or tree_status = "created"');
  });

  it("are no query without a status", () => {
    expect(treeStatusQuery("")).toBe("");
    expect(treeStatusQuery("", 5)).toBe("");
  });

  // Plan 31 §1: failed with a share keeps the trees failing at least N%.
  it("match failed by the tree's failure share when given one", () => {
    expect(treeStatusQuery("failed", 5)).toBe("failed_pct >= 5");
    expect(treeStatusQuery("stuck,failed", 12.5)).toBe('status = "stuck" or stuck_below > 0 or failed_pct >= 12.5');
    expect(treeStatusQuery("running", 5)).toBe('status = "running" or running_below > 0');
  });

  // Plan 34 §3: the lost chip keeps the trees with lost runs below them.
  it("add the lost chip's trees", () => {
    expect(treeStatusQuery("", null, true)).toBe("lost_below > 0");
    expect(treeStatusQuery("failed", 5, true)).toBe("failed_pct >= 5 or lost_below > 0");
    expect(treeStatusQuery("running", null, false)).toBe('status = "running" or running_below > 0');
  });
});
