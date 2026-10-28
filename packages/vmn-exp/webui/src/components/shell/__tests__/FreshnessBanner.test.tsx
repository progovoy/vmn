import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import FreshnessBanner from "../FreshnessBanner";
import type { Freshness } from "../../../util/freshness";

const DAY = 24 * 3600_000;
const freshness = (ageMs: number, extra: Partial<Freshness> = {}): Freshness => ({
  as_of: new Date(Date.now() - ageMs).toISOString(), refreshing: true,
  refresh_running_sec: 60, phase: "full_listing", progress: 0.45, refresh_failing: false,
  last_error: null, stale_after_sec: 300, ...extra,
});

describe("FreshnessBanner", () => {
  it("renders nothing while the data is fresh", () => {
    expect(render(<FreshnessBanner freshness={freshness(1000)} />).container).toBeEmptyDOMElement();
    expect(render(<FreshnessBanner />).container).toBeEmptyDOMElement();
  });

  it("announces stale data with the sync's progress", () => {
    render(<FreshnessBanner freshness={freshness(4 * DAY)} />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("freshness-banner", "stale");
    expect(banner).toHaveTextContent("(4d old). Syncing with the store — listing runs, ~45%.");
  });

  it("warns, not alarms, when runs could not be read from a throttling store", () => {
    render(<FreshnessBanner freshness={freshness(1000, { unreadable: {
      count: 12, store_errors: 12, last_error: "ClientError('... (SlowDown) ...')" } })} />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("freshness-banner", "stale");
    expect(banner).toHaveTextContent(
      "12 runs could not be read (the store is throttling: SlowDown); retrying.");
  });

  it("shows the error variant when the refresh does not complete", () => {
    render(<FreshnessBanner freshness={freshness(4 * DAY, {
      refresh_failing: true, refresh_running_sec: 1500, last_error: "OSError('x')" })} />);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveClass("freshness-banner", "error");
    expect(banner).toHaveTextContent("Data is 4d old and the background refresh has not "
      + "completed for 25m (last error: OSError('x')).");
  });
});
