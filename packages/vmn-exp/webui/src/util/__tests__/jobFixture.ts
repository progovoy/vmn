/** A Jobs-view row's compact job summary (plan 23 §10), for tests. */
import type { JobRolled, JobRollup } from "../../types";

export function job(extra: Partial<JobRollup> = {}): JobRollup {
  return {
    total: 1415, done: 1412, expected: 2000, progress: 0.706,
    counts: { running: 3, waiting: 0, succeeded: 1409, failed: 3, stuck: 0 },
    failed_pct: 0.21, throughput_per_min: 41, eta_sec: 840,
    metric: "val_loss", goal: "min", best: 0.182, best_verstr: "0.0.1-dev.t1903", best_idx: 1903,
    spread: [1, 2, 5, 9, 5, 2, 1, 0, 0, 0, 0, 1],
    progress_source: "runs", when_at: new Date(Date.now() - 86_400_000).toISOString(), when_source: "started",
    ...extra,
  };
}

export const NO_COUNTS = { running: 0, waiting: 0, succeeded: 0, failed: 0, stuck: 0 };

/** A job's `rolled` (plan 31 §2): by default the app default's, the best
 *  of its children's subtree bests. */
export function rolled(extra: Partial<JobRolled> = {}): JobRolled {
  return {
    agg: "best", by: "children", source: "best", metric: "val_loss", goal: "min", percentile: null,
    value: 0.182, n: 16, of: 16, conflicts: 0, verstr: "0.0.1-dev.t1903", approx: false,
    ...extra,
  };
}
