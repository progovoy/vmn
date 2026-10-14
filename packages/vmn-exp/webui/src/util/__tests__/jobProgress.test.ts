/** A job's progress line and run bar (plan 23 W1, §3.1). */
import { describe, it, expect } from "vitest";
import { fmtThroughput, jobBarSegments, jobEtaCell, jobProgressText, jobRateCell, jobSpoken } from "../jobProgress";
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

const ended = (extra = {}) => job({
  total: 20, done: 20, expected: 20, throughput_per_min: 0, eta_sec: null,
  counts: { ...NO_COUNTS, succeeded: 20 }, ...extra,
});
const DAYS_3 = () => new Date(Date.now() - 3 * 86_400_000 - 60_000).toISOString();

describe("a Jobs-view row's ETA cell", () => {
  it("is the time left while runs are in flight", () => {
    expect(jobEtaCell(job()).text).toBe("14m");
  });

  it("reads stalled while runs are left and none finishes", () => {
    const cell = jobEtaCell(job({ eta_sec: null, throughput_per_min: 0 }));
    expect(cell.text).toBe("stalled");
    expect(cell.title).toMatch(/no run finished/);
  });

  it("is when a finished job finished", () => {
    expect(jobEtaCell(ended({ finished_at: DAYS_3() })).text).toBe("finished 3d ago");
    expect(jobEtaCell(ended()).text).toBe("finished");
  });

  it("counts the runs an ended job never started", () => {
    const cell = jobEtaCell(ended({ expected: 200, finished_at: DAYS_3() }));
    expect(cell.text).toBe("ended · 180 never started");
  });

  it("stuck runs with nothing else in flight are a stall", () => {
    expect(jobEtaCell(ended({ counts: { ...NO_COUNTS, succeeded: 18, stuck: 2 } })).text).toBe("stalled");
  });
});

describe("a Jobs-view row's rate cell", () => {
  it("is the throughput while runs complete", () => {
    expect(jobRateCell(job()).text).toBe("41/min");
  });

  it("is a dash saying why once nothing completes", () => {
    expect(jobRateCell(ended())).toEqual({ text: "—", title: "the job has ended" });
    const stalled = jobRateCell(job({ throughput_per_min: 0, eta_sec: null }));
    expect(stalled.text).toBe("—");
    expect(stalled.title).toMatch(/no run finished/);
  });
});
