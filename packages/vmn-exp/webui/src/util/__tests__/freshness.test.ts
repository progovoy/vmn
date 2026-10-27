import { describe, it, expect } from "vitest";
import {
  freshnessBanner, freshnessShort, refreshingOnOldData, type Freshness,
} from "../freshness";

const AS_OF = "2026-10-22T19:44:00+00:00";
const AS_OF_MS = Date.parse(AS_OF);
const MIN = 60_000;
const DAY = 24 * 60 * MIN;
const fresh: Freshness = {
  as_of: AS_OF, refreshing: false, refresh_running_sec: null, phase: "idle", progress: null,
  refresh_failing: false, last_error: null, stale_after_sec: 300,
};
const syncing: Freshness = {
  ...fresh, refreshing: true, refresh_running_sec: 125, phase: "full_listing", progress: 0.45,
};

describe("freshnessBanner", () => {
  it("shows nothing once fresh data was published, or without freshness", () => {
    expect(freshnessBanner(fresh, AS_OF_MS + MIN)).toBeNull();
    expect(freshnessBanner({ ...syncing, phase: "journal", progress: null }, AS_OF_MS + 2 * MIN))
      .toBeNull();
    expect(freshnessBanner(undefined, AS_OF_MS)).toBeNull();
  });

  it("says how old the data is and how far the sync is", () => {
    expect(freshnessBanner(syncing, AS_OF_MS + 4 * DAY + 3 * MIN)).toEqual({
      kind: "stale",
      text: "⚠ Showing data as of Oct 22 19:44 UTC (4d old). Syncing with the store — "
        + "listing runs, ~45%. New runs will appear when it finishes.",
    });
  });

  it("names each phase, without a progress it does not know", () => {
    const at = AS_OF_MS + 10 * MIN;
    expect(freshnessBanner({ ...syncing, phase: "loading_new", progress: 0.5 }, at)?.text)
      .toContain("Syncing with the store — loading new runs, ~50%.");
    expect(freshnessBanner({ ...syncing, phase: "journal", progress: null }, at)?.text)
      .toContain("Syncing with the store — reading the change journal.");
  });

  it("says old data while no refresh runs", () => {
    expect(freshnessBanner(fresh, AS_OF_MS + 10 * MIN)?.text).toBe(
      "⚠ Showing data as of Oct 22 19:44 UTC (10m old).");
  });

  it("follows the configured threshold", () => {
    const lax = { ...fresh, stale_after_sec: 3600 };
    expect(freshnessBanner(lax, AS_OF_MS + 30 * MIN)).toBeNull();
    expect(freshnessBanner(lax, AS_OF_MS + 61 * MIN)?.kind).toBe("stale");
  });

  it("is an error when the refresh is stuck", () => {
    const stuck = { ...syncing, refresh_running_sec: 25 * 60 + 10, refresh_failing: true };
    expect(freshnessBanner(stuck, AS_OF_MS + 4 * DAY)).toEqual({
      kind: "error",
      text: "⚠ Data is 4d old and the background refresh has not completed for 25m.",
    });
  });

  it("is an error naming the last error when the refresh fails", () => {
    const failing = { ...fresh, refresh_failing: true, last_error: "OSError('reset')" };
    expect(freshnessBanner(failing, AS_OF_MS + 40 * MIN)).toEqual({
      kind: "error",
      text: "⚠ Data is 40m old and the background refresh has not completed for 40m "
        + "(last error: OSError('reset')).",
    });
  });

  it("leaves a fresh failure alone until the data is old", () => {
    expect(freshnessBanner({ ...fresh, refresh_failing: true }, AS_OF_MS + MIN)).toBeNull();
  });

  it("says a failing index with no data age is failing", () => {
    const failing = { ...fresh, as_of: null, refresh_failing: true, last_error: "x" };
    expect(freshnessBanner(failing, AS_OF_MS)).toEqual({
      kind: "error", text: "⚠ The background refresh has not completed (last error: x).",
    });
    expect(freshnessBanner({ ...syncing, as_of: null }, AS_OF_MS)).toBeNull();
  });
});

describe("freshnessShort", () => {
  it("is empty while fresh", () => {
    expect(freshnessShort(fresh, AS_OF_MS + MIN)).toBe("");
    expect(freshnessShort(undefined, AS_OF_MS)).toBe("");
  });
  it("says the age and the sync's progress", () => {
    expect(freshnessShort(syncing, AS_OF_MS + 4 * DAY)).toBe("data 4d old · syncing ~45%");
    expect(freshnessShort(fresh, AS_OF_MS + 10 * MIN)).toBe("data 10m old");
  });
  it("says a refresh that does not complete", () => {
    expect(freshnessShort({ ...syncing, refresh_failing: true }, AS_OF_MS + DAY)).toBe(
      "data 1d old · refresh not completing");
  });
});

describe("refreshingOnOldData", () => {
  it("is true only while a refresh runs on data past the threshold", () => {
    expect(refreshingOnOldData(syncing, AS_OF_MS + 10 * MIN)).toBe(true);
    expect(refreshingOnOldData(syncing, AS_OF_MS + MIN)).toBe(false);
    expect(refreshingOnOldData(fresh, AS_OF_MS + 10 * MIN)).toBe(false);
    expect(refreshingOnOldData(undefined, AS_OF_MS)).toBe(false);
  });
});
