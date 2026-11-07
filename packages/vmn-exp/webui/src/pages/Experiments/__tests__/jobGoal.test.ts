/** Plan 32 F4, plan 31 §2: `job:value` sorts toward the goal, and
 *  ascending without one (the goal itself is the rows' `rolled.goal`,
 *  JobsValueColumn.test.tsx). */
import { describe, it, expect } from "vitest";
import { jobValueOrder } from "../jobColumns";

describe("jobValueOrder", () => {
  it("sorts job:value toward the goal, ascending without one", () => {
    expect(jobValueOrder("job:value", "max")).toBe("desc");
    expect(jobValueOrder("job:value", "min")).toBe("asc");
    expect(jobValueOrder("job:value", null)).toBe("asc");
  });

  it("leaves the other columns to the board", () => {
    expect(jobValueOrder("job:total", "max")).toBeNull();
  });
});
