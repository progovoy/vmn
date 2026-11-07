/** Plan 32 F4/F5: the Jobs view's Best column takes its goal from the
 *  server's job rollup, never a guess; `job:best` sorts toward it, and
 *  ascending without one. */
import { describe, it, expect } from "vitest";
import type { ExperimentRow } from "../../../types";
import { job } from "../../../util/__tests__/jobFixture";
import { jobBestOrder, mainGoal } from "../jobColumns";

const jobRow = (goal: "min" | "max" | null) => ({ verstr: "v1", metrics: {}, job: job({ goal }) } as unknown as ExperimentRow);
const single = { verstr: "v2", metrics: { val_loss: 0.3 } } as unknown as ExperimentRow;

describe("mainGoal", () => {
  it("is the job rollup's goal, whatever the schema says", () => {
    expect(mainGoal([jobRow("max")], "val_loss", { val_loss: { goal: "min" } })).toBe("max");
    expect(mainGoal([jobRow(null)], "val_loss", { val_loss: { goal: "min" } })).toBeNull();
  });

  it("is the declared goal for single runs only, never one guessed from the name", () => {
    expect(mainGoal([single], "val_loss", { val_loss: { goal: "min" } })).toBe("min");
    expect(mainGoal([single], "val_loss", {})).toBeNull();
    expect(mainGoal([single], null, null)).toBeNull();
  });
});

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
