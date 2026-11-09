/** An upgrade's background check of compacted runs (freshness `checking`)
 *  is said on the dashboard and the boards' count line, fresh data or not. */
import { describe, it, expect } from "vitest";
import { freshnessBanner, freshnessShort, type Freshness } from "../freshness";

const AS_OF = "2026-10-22T19:44:00+00:00";
const AS_OF_MS = Date.parse(AS_OF);
const MIN = 60_000;
const fresh: Freshness = {
  as_of: AS_OF, refreshing: false, refresh_running_sec: null, phase: "idle", progress: null,
  refresh_failing: false, last_error: null, stale_after_sec: 300,
};
const checking = { ...fresh, checking: { done: 120_000, total: 734_000 } };

describe("an upgrade's check of compacted runs", () => {
  it("is a banner while fresh", () => {
    expect(freshnessBanner(checking, AS_OF_MS + MIN)).toEqual({
      kind: "stale",
      text: "Checking 120,000 / 734,000 compacted runs written by an older vmn-exp; "
        + "their rows show meanwhile.",
    });
  });

  it("joins the age banner of old data", () => {
    expect(freshnessBanner(checking, AS_OF_MS + 10 * MIN)?.text).toBe(
      "⚠ Showing data as of Oct 22 19:44 UTC (10m old). Checking 120,000 / 734,000 compacted "
      + "runs written by an older vmn-exp; their rows show meanwhile.");
  });

  it("is on the count line", () => {
    expect(freshnessShort(checking, AS_OF_MS + MIN)).toBe("checking 120,000/734,000 compacted runs");
    expect(freshnessShort(checking, AS_OF_MS + 10 * MIN))
      .toBe("data 10m old · checking 120,000/734,000 compacted runs");
  });

  it("says nothing without one", () => {
    expect(freshnessBanner(fresh, AS_OF_MS + MIN)).toBeNull();
    expect(freshnessShort(fresh, AS_OF_MS + MIN)).toBe("");
  });
});
