/** An outer run's declared progress (plan 28 P2): `progress`/`progress_total`
 *  on its own row lead its line and fill its bar; the run counts follow. */
import { describe, it, expect } from "vitest";
import { fmtRate, jobBarSegments, jobProgressText, jobRateCell, jobSpoken } from "../jobProgress";
import { job } from "./jobFixture";

const dates = (extra = {}) => job({
  progress: 0.6833, eta_sec: 840,
  declared_progress: { done: 41, total: 60, unit: "dates", rate_per_min: 0.34 },
  ...extra,
});

describe("a declared progress", () => {
  it("leads the line in its unit, the runs second", () => {
    expect(jobProgressText(dates())).toBe("41/60 dates · 1,415 runs · 3 failed · 20 dates/h · ETA 14m");
  });

  it("reads without a unit", () => {
    const bare = dates({ declared_progress: { done: 41, total: 60, unit: null, rate_per_min: 2 } });
    expect(jobProgressText(bare)).toBe("41/60 · 1,415 runs · 3 failed · 2/min · ETA 14m");
  });

  it("has a sentence for a screen reader", () => {
    expect(jobSpoken(dates())).toBe("41 of 60 dates done, 1,415 runs, 3 failed, 20 dates/h, about 14m left");
  });

  it("fills the bar with its share alone", () => {
    expect(jobBarSegments(dates())).toEqual([{ tone: "done", pct: 68.33 }]);
  });

  it("is the rate cell, a dash while nothing is done yet", () => {
    expect(jobRateCell(dates()).text).toBe("20 dates/h");
    const none = dates({ declared_progress: { done: 0, total: 60, unit: "dates", rate_per_min: 0 }, eta_sec: null });
    expect(jobRateCell(none).text).toBe("—");
  });

  it("leaves a job without one as before", () => {
    expect(jobProgressText(job({ declared_progress: null }))).toBe("1,412/2,000 · 3 failed · 41/min · ETA 14m");
  });
});

describe("fmtRate", () => {
  it("counts a minute from one a minute, an hour below, with the unit", () => {
    expect(fmtRate(41.25, "dates")).toBe("41 dates/min");
    expect(fmtRate(0.34, null)).toBe("20/h");
    expect(fmtRate(0.001, "dates")).toBe("0.1 dates/h");
  });
});
