import { describe, expect, it } from "vitest";
import { LIVE_QUERY, REVIEW_QUERY } from "../presets";

describe("the Live/Review presets", () => {
  // A container outer run that never ran itself, with a failed run and a
  // running one, reads tree_status failed: only its live runs keep it in flight.
  it("count an outer run with runs still live below it as in flight", () => {
    expect(LIVE_QUERY).toContain("live_below > 0");
    expect(REVIEW_QUERY).toMatch(/^not \(.*live_below > 0\)$/);
  });
});
