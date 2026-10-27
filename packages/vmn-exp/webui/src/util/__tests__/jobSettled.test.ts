/** An ended outer run settles what it left behind (job_rollup_payload.py):
 *  its never-started runs and lost (stuck) runs come beside the counts, the
 *  lost ones drawn and said as failures, the never-started ones as the
 *  empty track of `ended · N never started`. */
import { describe, it, expect } from "vitest";
import { jobBarSegments, jobEtaCell, jobProgressParts, jobProgressText } from "../jobProgress";
import { NO_COUNTS, job } from "./jobFixture";

const ago = (sec: number) => new Date(Date.now() - sec * 1000).toISOString();

const ended = job({
  expected: 10, total: 10, done: 7, never_started: 3, lost: 2, ended: true,
  eta_sec: 0, throughput_per_min: 0, finished_at: ago(60),
  counts: { ...NO_COUNTS, succeeded: 4, failed: 1 },
});

describe("an ended job's settled runs", () => {
  it("are lost, toned as failures, and never started", () => {
    expect(jobProgressText(ended)).toBe(`7/10 · 1 failed · 2 lost · ended ${"1m ago"} · 3 never started`);
    expect(jobProgressParts(ended).find((p) => p.text === "2 lost")?.tone).toBe("failed");
  });

  it("end the job however recently its last run finished", () => {
    expect(jobEtaCell(ended).text).toBe("ended · 3 never started");
  });

  it("draw the lost runs as failed and leave the never-started ones the empty track", () => {
    expect(jobBarSegments(ended)).toEqual([{ tone: "done", pct: 40 }, { tone: "failed", pct: 30 }]);
  });

  it("count toward the runs a bar measures against", () => {
    const segs = jobBarSegments(job({ expected: 2, never_started: 2, lost: 0, counts: { ...NO_COUNTS, succeeded: 2 } }));
    expect(segs).toEqual([{ tone: "done", pct: 50 }]);
  });
});
