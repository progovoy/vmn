/** One percent format for the Jobs view's Failed column, the KPI tile and
 *  the failure clusters' param shares. */
import { describe, it, expect } from "vitest";
import { fmtPct } from "../../../util";
import { jobKpis, paramShareText } from "../jobData";
import { jobNumbers } from "../../Experiments/JobCells";
import { job } from "../../../util/__tests__/jobFixture";
import { jobSummaryFixture } from "./jobFixture";

describe("fmtPct", () => {
  it("rounds to whole percent from 10, one decimal below", () => {
    expect(fmtPct(0)).toBe("0%");
    expect(fmtPct(0.21)).toBe("0.2%");
    expect(fmtPct(1.5)).toBe("1.5%");
    expect(fmtPct(33.3333)).toBe("33%");
    expect(fmtPct(100)).toBe("100%");
  });
});

describe("the job's failed share reads the same everywhere", () => {
  it("in the KPI tile and the Jobs view's Failed column", () => {
    const tile = jobKpis(jobSummaryFixture({ failed_pct: 33.3333 })).find((t) => t.label === "failed")!;
    expect(tile.value).toBe("33%");
    const row = { job: job({ failed_pct: 33.3333 }) } as Parameters<typeof jobNumbers>[0];
    expect(jobNumbers(row).failed).toMatchObject({ text: "33%" });
  });

  it("in a failure cluster's param shares", () => {
    expect(paramShareText({ key: "lr", value: 1, share: 0.015, base_share: 0.5 })).toBe("lr = 1 · 1.5% vs 50%");
  });
});
