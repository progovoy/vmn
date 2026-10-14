/** What a job's progress says (plan 23 W1, §3.1): `1,412/2,000 · 3 failed ·
 *  41/min · ETA 14m`, and its run bar over the expected runs. */
import type { JobSummary } from "../types";
import { fmtCount, humanizeSeconds, relTime } from "../util";
import { barSegments } from "../pages/groupHeaderText";

/** `41/min`; one decimal below 10 a minute (`0.3/min`). */
export function fmtThroughput(perMin: number): string {
  const n = perMin >= 10 ? Math.round(perMin) : Math.round(perMin * 10) / 10;
  return `${fmtCount(n)}/min`;
}

/** The job's completions a minute, null while nothing completes. */
export const throughputText = (j: Pick<JobSummary, "throughput_per_min">) => (j.throughput_per_min > 0 ? fmtThroughput(j.throughput_per_min) : null);

/** The time left, null when done or unknown. */
export const etaText = (j: Pick<JobSummary, "eta_sec">) => (j.eta_sec ? humanizeSeconds(j.eta_sec) : null);

type Progress = Pick<JobSummary, "counts" | "done" | "expected" | "throughput_per_min" | "eta_sec">
  & { finished_at?: string | null };

export interface ProgressPart {
  text: string;
  tone?: "failed" | "stuck";
}

/** Where the job stands in time: `ETA 14m`; `stalled` while runs run and
 *  none completes; `ended 21d ago · 180 never started` once nothing runs
 *  short of the expected; `finished 2h ago` when complete. */
function timeParts(j: Progress, eta: (left: string) => string): string[] {
  const when = j.finished_at ? ` ${relTime(j.finished_at)}` : "";
  const left = j.expected - j.done;
  if (left <= 0) return when ? [`finished${when}`] : [];
  const etaLeft = etaText(j);
  if (etaLeft) return [eta(etaLeft)];
  if (j.counts.running > 0) return ["stalled"];
  const never = left - j.counts.stuck;
  return [`ended${when}`, never > 0 ? `${fmtCount(never)} never started` : ""].filter(Boolean);
}

function parts(j: Progress, done: string, eta: (left: string) => string): ProgressPart[] {
  const troubles = (["failed", "stuck"] as const)
    .filter((t) => j.counts[t] > 0).map((t): ProgressPart => ({ text: `${fmtCount(j.counts[t])} ${t}`, tone: t }));
  const rate = throughputText(j);
  return [{ text: done }, ...troubles, ...(rate ? [{ text: rate }] : []), ...timeParts(j, eta).map((text) => ({ text }))];
}

/** The progress line's parts, failed and stuck toned (the job header's). */
export const jobProgressParts = (j: Progress) =>
  parts(j, `${fmtCount(j.done)}/${fmtCount(j.expected)}`, (left) => `ETA ${left}`);

export const jobProgressText = (j: Progress) => jobProgressParts(j).map((p) => p.text).join(" · ");

/** The same, for a screen reader. */
export const jobSpoken = (j: Progress) =>
  parts(j, `${fmtCount(j.done)} of ${fmtCount(j.expected)} runs done`, (left) => `about ${left} left`)
    .map((p) => p.text).join(", ");

/** Each state's share (percent) of the expected runs (of the runs so far,
 *  once more ran than expected), like a group header's bar; the rest is
 *  the empty track. Null for a job of one run or none. */
export function jobBarSegments(j: Pick<JobSummary, "counts" | "expected">) {
  const c = j.counts;
  const of = Math.max(j.expected, c.running + c.waiting + c.succeeded + c.failed + c.stuck);
  return barSegments({ total: of, done: c.succeeded, failed: c.failed, stuck: c.stuck, running: c.running });
}

/** What a Jobs-view cell shows, and its tooltip. */
export interface JobCell { text: string; title: string }

const STALLED_TITLE = "no run finished in the last 10 minutes";

/** Runs waiting, running or stuck: the job has not ended. */
const inFlight = (j: JobSummary) => j.counts.running + j.counts.waiting + j.counts.stuck > 0;

/** `14m` left, `stalled`, `finished 3d ago` or `ended · 180 never started`. */
export function jobEtaCell(j: JobSummary): JobCell {
  const left = etaText(j);
  if (inFlight(j)) {
    return left ? { text: left, title: `about ${left} left` } : { text: "stalled", title: STALLED_TITLE };
  }
  const never = j.expected - j.total;
  if (never > 0) return { text: `ended · ${fmtCount(never)} never started`, title: "the job has ended" };
  const when = relTime(j.finished_at);
  return { text: when ? `finished ${when}` : "finished", title: j.finished_at ?? "the job has finished" };
}

/** `41/min`, else a dash saying why nothing completes. */
export function jobRateCell(j: JobSummary): JobCell {
  const rate = throughputText(j);
  if (rate) return { text: rate, title: "runs finished a minute, over the last 10 minutes" };
  return { text: "—", title: inFlight(j) ? STALLED_TITLE : "the job has ended" };
}
