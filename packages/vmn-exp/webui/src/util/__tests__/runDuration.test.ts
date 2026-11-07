/** Plan 32 F13: a run's duration names what it is — final, elapsed while
 *  running, or only a lower bound for a run that ended without a recorded
 *  end (`≥ 3h (stuck)`). */
import { describe, expect, it } from "vitest";
import { runDurationText } from "../runDuration";

describe("runDurationText", () => {
  it("shows a final duration as it is", () => {
    expect(runDurationText({ status: "succeeded", duration_sec: 7300 })).toEqual(["2h", "7300 s"]);
  });

  it("marks a running run's elapsed time", () => {
    expect(runDurationText({ status: "running", duration_sec: 600 }))
      .toEqual(["10m (running)", "600 s so far: still running"]);
  });

  it("shows a lower bound with the status that cut it short", () => {
    const [text, title] = runDurationText({ status: "stuck", duration_sec: null, duration_at_least_sec: 11000 });
    expect(text).toBe("≥ 3h (stuck)");
    expect(title).toBe("at least 11000 s: stuck, it recorded no end");
  });

  it("shows a dash when neither is known", () => {
    expect(runDurationText({ status: "created", duration_sec: null })).toEqual(["—", undefined]);
  });
});
