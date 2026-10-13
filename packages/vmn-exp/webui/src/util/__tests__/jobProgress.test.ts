/** A job's progress line and run bar (plan 23 W1, §3.1). */
import { describe, it, expect } from "vitest";
import { fmtThroughput, jobBarSegments, jobProgressText, jobSpoken } from "../jobProgress";
import { NO_COUNTS, job } from "./jobFixture";

describe("jobProgressText", () => {
  it("reads done/expected, failures, throughput and ETA", () => {
    expect(jobProgressText(job())).toBe("1,412/2,000 · 3 failed · 41/min · ETA 14m");
  });

  it("leaves out what is zero or unknown", () => {
    const done = job({
      done: 5, expected: 5, total: 5, throughput_per_min: 0, eta_sec: 0,
      counts: { ...NO_COUNTS, succeeded: 5 },
    });
    expect(jobProgressText(done)).toBe("5/5");
    expect(jobProgressText(job({ eta_sec: null }))).toBe("1,412/2,000 · 3 failed · 41/min");
  });

  it("names stuck runs next to failed ones", () => {
    const stuck = job({ counts: { ...NO_COUNTS, succeeded: 1409, failed: 3, stuck: 2 } });
    expect(jobProgressText(stuck)).toContain("3 failed · 2 stuck");
  });

  it("has a sentence for a screen reader", () => {
    expect(jobSpoken(job())).toBe("1,412 of 2,000 runs done, 3 failed, 41/min, about 14m left");
  });
});

describe("fmtThroughput", () => {
  it("rounds to whole runs from 10 a minute, one decimal below", () => {
    expect(fmtThroughput(41.25)).toBe("41/min");
    expect(fmtThroughput(0.34)).toBe("0.3/min");
    expect(fmtThroughput(1200)).toBe("1,200/min");
  });
});

describe("jobBarSegments", () => {
  it("fills each state's share of the expected runs, the rest the empty track", () => {
    const segs = jobBarSegments(job({
      expected: 10, counts: { running: 1, waiting: 2, succeeded: 5, failed: 1, stuck: 1 },
    }));
    expect(segs).toEqual([
      { tone: "done", pct: 50 }, { tone: "failed", pct: 10 }, { tone: "stuck", pct: 10 }, { tone: "running", pct: 10 },
    ]);
  });

  it("measures against the runs so far once they outnumber the expected", () => {
    const segs = jobBarSegments(job({ expected: 2, counts: { ...NO_COUNTS, succeeded: 4 } }));
    expect(segs).toEqual([{ tone: "done", pct: 100 }]);
  });

  it("draws nothing for an empty job", () => {
    expect(jobBarSegments(job({ expected: 0, counts: NO_COUNTS }))).toBeNull();
  });
});
