/** The run page paints first from the leaderboard's cached row; an
 *  incomplete sweep's fields must survive that summary (plan 20 D12). */
import { describe, it, expect } from "vitest";
import { sweepIncompleteLabel } from "../../util/sweepProgress";
import { summaryFromRow } from "../runSummary";
import { row } from "./leaderboardHarness";

describe("summaryFromRow of a sweep", () => {
  it("keeps the planned and filled trial counts", () => {
    const summary = summaryFromRow(row(2, {
      kind: "outer", children: ["a"], status: "created", tree_status: "created",
      sweep_planned: 20, sweep_trials: 16,
    }));
    expect(sweepIncompleteLabel(summary.status!)).toBe("16/20 · incomplete");
  });
});
