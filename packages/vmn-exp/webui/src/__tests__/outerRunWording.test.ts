import { describe, expect, it } from "vitest";
import { JOB_COLUMNS } from "../pages/Experiments/jobColumns";
import { kindNoun } from "../pages/Experiments/jobsKind";
import { jobEtaCell } from "../util/jobProgress";
import type { JobCounts } from "../types";

const counts = (c: Partial<JobCounts> = {}): JobCounts =>
  ({ running: 0, waiting: 0, succeeded: 0, failed: 0, stuck: 0, ...c });

describe("outer run wording (the CLI's kind = \"outer\")", () => {
  it("heads the name column outer run · progress", () => {
    expect(JOB_COLUMNS.find((c) => c.id === "name")?.label).toBe("outer run · progress");
  });

  it("names the listed kind an outer run", () => {
    expect(kindNoun("jobs")).toBe("outer run");
  });

  it("says a finished outer run has finished", () => {
    const cell = jobEtaCell({
      counts: counts({ succeeded: 2 }), done: 2, expected: 2, throughput_per_min: 0, eta_sec: 0, finished_at: null,
    });
    expect(cell.title).toBe("the outer run has finished");
  });
});
