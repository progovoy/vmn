import { describe, it, expect } from "vitest";
import type { AppStatus } from "../contracts";
import type { Freshness } from "../../util/freshness";
import { statusPollMs } from "../useShellData";

const MIN = 60_000;
const freshness = (ageMs: number, refreshing: boolean): Freshness => ({
  as_of: new Date(Date.now() - ageMs).toISOString(), refreshing,
  refresh_running_sec: refreshing ? 30 : null, phase: refreshing ? "full_listing" : "idle",
  progress: null, refresh_failing: false, last_error: null, stale_after_sec: 300,
});
const status = (f: Freshness): AppStatus => ({
  total: 1, counts: { created: 0, running: 0, stuck: 0, succeeded: 1, failed: 0 },
  failed_recent: 0, rollup: null, freshness: f,
});

describe("status polling by freshness", () => {
  it("polls every 2 s while a refresh runs on old data", () => {
    expect(statusPollMs(status(freshness(4 * 24 * 60 * MIN, true)))).toBe(2_000);
  });
  it("polls as usual while the data is fresh, or no refresh runs", () => {
    expect(statusPollMs(status(freshness(MIN, true)))).toBe(60_000);
    expect(statusPollMs(status(freshness(10 * MIN, false)))).toBe(60_000);
  });
});
