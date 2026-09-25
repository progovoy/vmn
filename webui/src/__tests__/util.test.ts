import { describe, it, expect, vi, afterEach } from "vitest";
import { fmtDuration, fmtVal, humanizeSeconds, pollIntervalMs, relTime } from "../util";

describe("humanizeSeconds", () => {
  it("walks the s/m/h/d ladder", () => {
    expect(humanizeSeconds(0)).toBe("0s");
    expect(humanizeSeconds(42)).toBe("42s");
    expect(humanizeSeconds(59.6)).toBe("59s");
    expect(humanizeSeconds(60)).toBe("1m");
    expect(humanizeSeconds(7 * 60)).toBe("7m");
    expect(humanizeSeconds(3599)).toBe("59m");
    expect(humanizeSeconds(2 * 3600)).toBe("2h");
    expect(humanizeSeconds(3 * 86400)).toBe("3d");
  });
});

describe("fmtDuration / relTime share one ladder", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("formats a null duration as a dash", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(undefined)).toBe("—");
  });

  it("formats a duration with no suffix", () => {
    expect(fmtDuration(42)).toBe("42s");
    expect(fmtDuration(7 * 60)).toBe("7m");
  });

  it("formats an empty or unparsable timestamp", () => {
    expect(relTime(null)).toBe("");
    expect(relTime("nonsense")).toBe("nonsense");
  });

  it("never disagrees with fmtDuration about the same span", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-01-02T00:00:00Z"));
    for (const secs of [0, 30, 59.6, 60, 119, 3599, 3600, 90000]) {
      const iso = new Date(Date.now() - secs * 1000).toISOString();
      expect(relTime(iso)).toBe(`${fmtDuration(secs)} ago`);
    }
  });
});

describe("fmtVal", () => {
  it("returns integers as plain strings, not scientific notation", () => {
    expect(fmtVal(20260531)).toBe("20260531");
    expect(fmtVal(1000)).toBe("1000");
    expect(fmtVal(999999999)).toBe("999999999");
    expect(fmtVal(0)).toBe("0");
    expect(fmtVal(-42)).toBe("-42");
  });

  it("still formats small floats in scientific notation", () => {
    expect(fmtVal(0.00001)).toBe("1.000e-5");
  });

  it("returns a dash for null/undefined", () => {
    expect(fmtVal(null)).toBe("–");
    expect(fmtVal(undefined)).toBe("–");
  });

  it("returns strings verbatim", () => {
    expect(fmtVal("hello")).toBe("hello");
  });
});

describe("pollIntervalMs", () => {
  it("defaults when the payload reports no heartbeat interval", () => {
    expect(pollIntervalMs(null)).toBe(15000);
    expect(pollIntervalMs(undefined)).toBe(15000);
  });

  it("follows half the heartbeat interval", () => {
    expect(pollIntervalMs(30)).toBe(15000);
    expect(pollIntervalMs(60)).toBe(30000);
  });

  it("floors at 5s so a fast heartbeat still feels live", () => {
    expect(pollIntervalMs(5)).toBe(5000);
    expect(pollIntervalMs(1)).toBe(5000);
  });
});
