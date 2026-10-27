/** An ended outer run's lost runs (stuck when it ended, job_rollup_payload.py)
 *  are failures: the failed tile and the failure clusters count them. */
import { describe, it, expect } from "vitest";
import { failedCount, jobKpis } from "../jobData";
import { jobSummaryFixture } from "./jobFixture";

const ended = jobSummaryFixture({
  ended: true, lost: 4, never_started: 6,
  counts: { running: 0, waiting: 0, succeeded: 1409, failed: 3, stuck: 1 },
});

describe("an ended outer run's lost runs", () => {
  it("count among the runs the failure clusters cover", () => {
    expect(failedCount(ended)).toBe(3 + 1 + 4);
  });

  it("count in the failed tile's runs", () => {
    expect(jobKpis(ended).find((t) => t.label === "failed")?.sub).toBe("7 runs");
  });
});
