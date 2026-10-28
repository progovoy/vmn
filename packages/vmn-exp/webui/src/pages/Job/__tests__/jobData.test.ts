import { describe, it, expect } from "vitest";
import {
  failureQuery, jobKpis, mainMetric, paramShareText, quantileMarks, rerunCommand,
  timelineSeries,
} from "../jobData";
import { jobSummaryFixture } from "./jobFixture";

describe("timelineSeries", () => {
  it("derives running(t) = cumulative started - cumulative ended, and completions per minute", () => {
    const s = timelineSeries({
      bucket_sec: 120, start: 1000,
      buckets: [
        { t: 1000, started: 4, succeeded: 0, failed: 0 },
        { t: 1120, started: 2, succeeded: 3, failed: 1 },
        { t: "1970-01-01T00:20:40Z", started: 0, succeeded: 1, failed: 0 },
      ],
    });
    expect(s.t).toEqual([1000_000, 1120_000, 1240_000]);
    expect(s.running).toEqual([4, 2, 1]);
    expect(s.succeeded).toEqual([0, 3, 4]);
    expect(s.failed).toEqual([0, 1, 1]);
    expect(s.perMin).toEqual([0, 2, 0.5]);
  });

  it("counts runs released per minute, zero where a bucket names none", () => {
    const s = timelineSeries({
      bucket_sec: 120, start: 0,
      buckets: [{ t: 0, started: 3, succeeded: 0, failed: 0 }, { t: 240, started: 0, succeeded: 0, failed: 0, released: 4 }],
    });
    expect(s.released).toEqual([0, 0, 2]);
    expect(s.running).toEqual([3, 3, 3]);
  });

  it("fills the empty buckets a sparse timeline leaves out with zeros", () => {
    const s = timelineSeries({
      bucket_sec: 60, start: 0,
      buckets: [{ t: 0, started: 3, succeeded: 0, failed: 0 }, { t: 180, started: 0, succeeded: 2, failed: 1 }],
    });
    expect(s.t).toEqual([0, 60_000, 120_000, 180_000]);
    expect(s.running).toEqual([3, 3, 3, 0]);
    expect(s.succeeded).toEqual([0, 0, 0, 2]);
    expect(s.failed).toEqual([0, 0, 0, 1]);
    expect(s.perMin).toEqual([0, 0, 0, 3]);
  });

  it("keeps a short timeline's rate per bucket (an average over one bucket)", () => {
    const s = timelineSeries({
      bucket_sec: 60, start: 0,
      buckets: [{ t: 0, started: 3, succeeded: 1, failed: 0 }, { t: 60, started: 0, succeeded: 2, failed: 0 }],
    });
    expect(s.rateWindow).toBe(1);
    expect(s.perMinAvg).toEqual([1, 2]);
  });

  it("smooths a long timeline's rate with a trailing average over ~1/120 of its buckets", () => {
    // 2 days of minutes: 2880 buckets, a 24-minute window; one run ends every other minute.
    const buckets = Array.from({ length: 2880 }, (_, i) => ({ t: i * 60, started: 1, succeeded: i % 2, failed: 0 }));
    const s = timelineSeries({ bucket_sec: 60, start: 0, buckets });
    expect(s.rateWindow).toBe(24);
    expect(s.perMin.slice(-2)).toEqual([0, 1]);
    expect(s.perMinAvg[0]).toBe(0);
    expect(s.perMinAvg[1]).toBe(0.5);
    expect(s.perMinAvg.slice(23)).toEqual(s.perMinAvg.slice(23).map(() => 0.5));
  });

  it("never reports fewer than zero running", () => {
    const s = timelineSeries({ bucket_sec: 60, start: 0, buckets: [{ t: 0, started: 0, succeeded: 2, failed: 0 }] });
    expect(s.running).toEqual([0]);
  });
});

describe("jobKpis", () => {
  it("names done/expected, failures, the live states, durations and the best run", () => {
    const tiles = jobKpis(jobSummaryFixture());
    const byLabel = Object.fromEntries(tiles.map((t) => [t.label, t]));
    expect(byLabel["done"].value).toBe("1,412");
    expect(byLabel["done"].sub).toBe("of 2,000");
    expect(byLabel["failed"].value).toBe("1.5%");
    expect(byLabel["failed"].sub).toBe("3 runs");
    expect(byLabel["running"].value).toBe("40");
    expect(byLabel["waiting"].value).toBe("548");
    expect(byLabel["stuck"].value).toBe("0");
    expect(byLabel["median duration"].value).toBe("2m");
    expect(byLabel["p90 duration"].value).toBe("7m");
    expect(byLabel["best val_loss"].value).toBe("0.182");
    expect(byLabel["best val_loss"].href).toBe("0.0.2-dev.t1903");
  });

  it("has no best tile when nothing is ranked (no goal declared)", () => {
    const tiles = jobKpis(jobSummaryFixture({ ranked: false }));
    expect(tiles.map((t) => t.label)).not.toContain("best val_loss");
  });
});

describe("mainMetric", () => {
  it("takes the server's metric, else the first tracked one with values", () => {
    expect(mainMetric(jobSummaryFixture())).toBe("val_loss");
    expect(mainMetric({ ...jobSummaryFixture(), metric: undefined, metrics: { a: null, b: jobSummaryFixture().metrics.val_loss } })).toBe("b");
    expect(mainMetric({ ...jobSummaryFixture(), metric: null, metrics: {} })).toBeNull();
  });
});

describe("failure helpers", () => {
  it("quotes a signature for the query language", () => {
    expect(failureQuery("failed | exit=<n>")).toBe('failure_sig = "failed | exit=<n>"');
    expect(failureQuery('msg="x"')).toBe(`failure_sig = 'msg="x"'`);
  });

  it("says how overrepresented a param is", () => {
    expect(paramShareText({ key: "batch_size", value: 512, share: 0.94, base_share: 0.25 }))
      .toBe("batch_size = 512 · 94% vs 25%");
    expect(paramShareText({ key: "opt", value: "adam", share: 1, base_share: 0.5 }))
      .toBe("opt = adam · 100% vs 50%");
  });

  it("copies a rerun command per example", () => {
    expect(rerunCommand("my/app", "0.0.2-dev.t1")).toBe("vmn-exp rerun my/app -v 0.0.2-dev.t1");
    expect(rerunCommand("a", "v", "s3://b/p")).toBe("vmn-exp rerun a -v v --store s3://b/p");
  });
});

describe("quantileMarks", () => {
  it("places p10/p50/p90 along the histogram range", () => {
    expect(quantileMarks({ ...jobSummaryFixture().metrics.val_loss!, min: 0, max: 1, hist: [
      { lo: 0, hi: 0.5, count: 1 }, { lo: 0.5, hi: 1, count: 1 },
    ], p10: 0.1, p50: 0.5, p90: 0.9 })).toEqual([
      { label: "p10", value: 0.1, at: 0.1 }, { label: "p50", value: 0.5, at: 0.5 }, { label: "p90", value: 0.9, at: 0.9 },
    ]);
  });

  it("skips missing quantiles", () => {
    expect(quantileMarks({ ...jobSummaryFixture().metrics.val_loss!, p10: null, p50: undefined, p90: null })).toEqual([]);
  });
});
