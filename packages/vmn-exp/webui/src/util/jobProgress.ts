/** What a job's progress says (plan 23 W1, §3.1): `1,412/2,000 · 3 failed ·
 *  41/min · ETA 14m`, and its run bar over the expected runs. */
import type { JobSummary } from "../types";
import { fmtCount, humanizeSeconds } from "../util";
import { barSegments } from "../pages/groupHeaderText";

/** `41/min`; one decimal below 10 a minute (`0.3/min`). */
export function fmtThroughput(perMin: number): string {
  const n = perMin >= 10 ? Math.round(perMin) : Math.round(perMin * 10) / 10;
  return `${fmtCount(n)}/min`;
}

/** The job's completions a minute, null while nothing completes. */
export const throughputText = (j: JobSummary) => (j.throughput_per_min > 0 ? fmtThroughput(j.throughput_per_min) : null);

/** The time left, null when done or unknown. */
export const etaText = (j: JobSummary) => (j.eta_sec ? humanizeSeconds(j.eta_sec) : null);

function parts(j: JobSummary, done: string, eta: (left: string) => string): string[] {
  const left = etaText(j);
  const troubles = (["failed", "stuck"] as const)
    .filter((t) => j.counts[t] > 0).map((t) => `${fmtCount(j.counts[t])} ${t}`);
  return [done, ...troubles, throughputText(j), left && eta(left)].filter((p): p is string => Boolean(p));
}

export const jobProgressText = (j: JobSummary) =>
  parts(j, `${fmtCount(j.done)}/${fmtCount(j.expected)}`, (left) => `ETA ${left}`).join(" · ");

/** The same, for a screen reader. */
export const jobSpoken = (j: JobSummary) =>
  parts(j, `${fmtCount(j.done)} of ${fmtCount(j.expected)} runs done`, (left) => `about ${left} left`).join(", ");

/** Each state's share (percent) of the expected runs (of the runs so far,
 *  once more ran than expected), like a group header's bar; the rest is
 *  the empty track. Null for a job of one run or none. */
export function jobBarSegments(j: JobSummary) {
  const c = j.counts;
  const of = Math.max(j.expected, c.running + c.waiting + c.succeeded + c.failed + c.stuck);
  return barSegments({ total: of, done: c.succeeded, failed: c.failed, stuck: c.stuck, running: c.running });
}
