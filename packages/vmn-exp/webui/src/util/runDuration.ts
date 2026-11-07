/** A run's duration for display (plan 32 F13), naming what it is: the final
 *  one, the elapsed time while running, or a lower bound for a run that
 *  ended without a recorded end (`≥ 3h (stuck)`). */
import type { RunStatus } from "../types";
import { fmtDuration } from "../util";

type Durations = Partial<Pick<RunStatus, "status" | "duration_sec" | "duration_at_least_sec">>;

/** `[text, title]` of a run's duration. */
export function runDurationText(r: Durations): [string, string | undefined] {
  const { status, duration_sec: sec, duration_at_least_sec: atLeast } = r;
  if (sec != null) {
    return status === "running"
      ? [`${fmtDuration(sec)} (running)`, `${sec} s so far: still running`]
      : [fmtDuration(sec), `${sec} s`];
  }
  if (atLeast != null) {
    return [`≥ ${fmtDuration(atLeast)} (${status})`, `at least ${atLeast} s: ${status}, it recorded no end`];
  }
  return ["—", undefined];
}
