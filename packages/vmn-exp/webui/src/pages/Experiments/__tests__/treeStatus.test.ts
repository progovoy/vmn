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
  });
});
