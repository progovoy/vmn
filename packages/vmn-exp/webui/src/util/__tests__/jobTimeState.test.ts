/** One classifier of where a job stands in time, which the job header's
 *  progress line and the Jobs view's ETA cell both render. */
import { describe, it, expect } from "vitest";
import { jobEtaCell, jobProgressText, jobTimeState } from "../jobProgress";
import { NO_COUNTS, job } from "./jobFixture";

const ago = (sec: number) => new Date(Date.now() - sec * 1000).toISOString();

describe("jobTimeState", () => {
  it("is the time left while runs are in flight", () => {
    expect(jobTimeState(job())).toEqual({ kind: "eta", left: "14m" });
  });

  it("is a stall while runs are in flight and none finishes", () => {
    expect(jobTimeState(job({ eta_sec: null, throughput_per_min: 0 }))).toEqual({ kind: "stalled" });
  });

  it("is ended, with the runs never started, once nothing is in flight short of the expected", () => {
    const ended = job({
      expected: 200, done: 20, total: 20, eta_sec: null, throughput_per_min: 0, finished_at: ago(3600),
      counts: { ...NO_COUNTS, succeeded: 20 },
    });
    expect(jobTimeState(ended)).toEqual({ kind: "ended", never: 180 });
  });

  it("is finished when every expected run is done", () => {
    const done = job({ expected: 5, done: 5, total: 5, eta_sec: null, counts: { ...NO_COUNTS, succeeded: 5 } });
    expect(jobTimeState(done)).toEqual({ kind: "finished" });
  });
});

describe("the header and the row read one state", () => {
  it("call a job with runs waiting and none finishing stalled, not ended", () => {
    const waiting = job({
      done: 10, expected: 20, total: 20, eta_sec: null, throughput_per_min: 0, finished_at: ago(60),
      counts: { ...NO_COUNTS, succeeded: 10, waiting: 10 },
    });
    expect(jobEtaCell(waiting).text).toBe("stalled");
    expect(jobProgressText(waiting)).toBe("10/20 · stalled");
  });
});
