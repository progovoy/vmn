/** Plan 32 F4: `job:best` sorts toward the goal, and ascending without
 *  one (the goal itself is the page's `main`, JobsMainMetric.test.tsx). */
import { describe, it, expect } from "vitest";
import { jobBestOrder } from "../jobColumns";

describe("jobBestOrder", () => {
  it("sorts job:best toward the goal, ascending without one", () => {
    expect(jobBestOrder("job:best", "max")).toBe("desc");
    expect(jobBestOrder("job:best", "min")).toBe("asc");
    expect(jobBestOrder("job:best", null)).toBe("asc");
  });

  it("leaves the other columns to the board", () => {
    expect(jobBestOrder("job:total", "max")).toBeNull();
  });
});
