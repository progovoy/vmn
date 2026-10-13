/** A Jobs-view row's compact job summary (plan 23 §10), for tests. */
import type { JobSummary } from "../../types";

export function job(extra: Partial<JobSummary> = {}): JobSummary {
  return {
    total: 1415, done: 1412, expected: 2000, progress: 0.706,
    counts: { running: 3, waiting: 0, succeeded: 1409, failed: 3, stuck: 0 },
    failed_pct: 0.21, throughput_per_min: 41, eta_sec: 840,
    metric: "val_loss", best: 0.182, best_verstr: "0.0.1-dev.t1903", best_idx: 1903,
    spread: [1, 2, 5, 9, 5, 2, 1, 0, 0, 0, 0, 1],
    ...extra,
  };
}

export const NO_COUNTS = { running: 0, waiting: 0, succeeded: 0, failed: 0, stuck: 0 };
