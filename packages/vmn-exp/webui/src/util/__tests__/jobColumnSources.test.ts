/** Plan 32 F2/F3/F14: each Jobs cell shows what its column sorts, and a
 *  value that has two sources reads from the one the row shows. */
import { describe, it, expect } from "vitest";
import { jobEtaCell, jobProgressText, jobRateCell, jobThroughputCell, jobTimeState } from "../jobProgress";
import { jobWhen } from "../jobWhen";
import { NO_COUNTS, job } from "./jobFixture";

const ago = (sec: number) => new Date(Date.now() - sec * 1000).toISOString();
const DATES = { done: 41, total: 60, unit: "dates", rate_per_min: 0.34 };

describe("the rate and throughput cells", () => {
  it("rate is the declared progress a minute, a dash without one", () => {
    expect(jobRateCell(job({ declared_progress: DATES })).text).toBe("20 dates/h");
    expect(jobRateCell(job({ declared_progress: null }))).toEqual({ text: "—", title: "no declared progress" });
  });

  it("throughput is the runs a minute, declared progress or not", () => {
    expect(jobThroughputCell(job({ declared_progress: DATES })).text).toBe("41/min");
    expect(jobThroughputCell(job({ declared_progress: null })).text).toBe("41/min");
  });
});

describe("a declared progress's time state", () => {
  const ended = (declared: typeof DATES) => job({
    declared_progress: declared, expected: 20, done: 20, total: 20, eta_sec: 0, throughput_per_min: 0,
    finished_at: ago(3 * 86400), counts: { ...NO_COUNTS, succeeded: 20 },
  });

  it("is unfinished in its unit when it ended short of its total, whatever the runs did", () => {
    expect(jobTimeState(ended(DATES))).toEqual({ kind: "unfinished", left: 19, unit: "dates" });
    expect(jobEtaCell(ended(DATES)).text).toBe("ended · 19 dates not done");
    expect(jobProgressText(ended(DATES))).toMatch(/· ended 3d ago · 19 dates not done$/);
  });

  it("is finished when its total is done, though runs never started", () => {
    const done = job({ ...ended({ ...DATES, done: 60 }), expected: 200 });
    expect(jobTimeState(done)).toEqual({ kind: "finished" });
  });
});

describe("a row's when", () => {
  it("is a job's when_at with its source", () => {
    const at = ago(3600);
    expect(jobWhen({ job: job({ when_at: at, when_source: "created" }), started_at: ago(60), timestamp: ago(60) }))
      .toEqual({ at, created: true });
    expect(jobWhen({ job: job({ when_at: at, when_source: "started" }), started_at: null, timestamp: ago(60) }))
      .toEqual({ at, created: false });
  });

  it("is a single run's start, else its creation, labelled created", () => {
    const at = ago(3600);
    expect(jobWhen({ job: null, started_at: at, timestamp: ago(7200) })).toEqual({ at, created: false });
    expect(jobWhen({ job: null, started_at: null, timestamp: at })).toEqual({ at, created: true });
  });
});
