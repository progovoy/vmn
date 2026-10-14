/** What a job's progress says (plan 23 W1, §3.1): `1,412/2,000 · 3 failed ·
 *  41/min · ETA 14m`, and its run bar over the expected runs. */
import type { JobProgressFields } from "../types";
import { fmtCount, humanizeSeconds, relTime } from "../util";
import { barSegments } from "../pages/groupHeaderText";
import { joinParts } from "./toneParts";

/** `41/min`; one decimal below 10 a minute (`0.3/min`). */
export function fmtThroughput(perMin: number): string {
  const n = perMin >= 10 ? Math.round(perMin) : Math.round(perMin * 10) / 10;
  return `${fmtCount(n)}/min`;
}

/** The job's completions a minute, null while nothing completes. */
export const throughputText = (j: Pick<JobProgressFields, "throughput_per_min">) => (j.throughput_per_min > 0 ? fmtThroughput(j.throughput_per_min) : null);

/** The time left, null when done or unknown. */
export const etaText = (j: Pick<JobProgressFields, "eta_sec">) => (j.eta_sec ? humanizeSeconds(j.eta_sec) : null);

type Progress = Pick<JobProgressFields, "counts" | "done" | "expected" | "throughput_per_min" | "eta_sec" | "finished_at">;

export interface ProgressPart {
  text: string;
  tone?: "failed" | "stuck";
}

/** Nothing running and no run finished for this long: the job has ended,
 *  whatever is still waiting or stuck. */
const QUIET_MS = 3_600_000;
const quiet = (j: Progress) =>
  j.counts.running === 0 && Boolean(j.finished_at) && Date.now() - Date.parse(j.finished_at!) > QUIET_MS;

/** Runs waiting, running or stuck, and not quiet for long: the job has not ended. */
const inFlight = (j: Progress) =>
  j.counts.running + j.counts.waiting + j.counts.stuck > 0 && !quiet(j);

/** Where a job stands in time: runs in flight with the time *left*, or
 *  none finishing (stalled); ended short of the expected with *never* runs
 *  never started; or finished. */
export type JobTimeState =
  | { kind: "eta"; left: string }
  | { kind: "stalled" }
  | { kind: "ended"; never: number }
  | { kind: "finished" };

export function jobTimeState(j: Progress): JobTimeState {
  if (inFlight(j)) {
    const left = etaText(j);
    return left ? { kind: "eta", left } : { kind: "stalled" };
  }
  const never = j.expected - j.done - j.counts.stuck;
  return never > 0 ? { kind: "ended", never } : { kind: "finished" };
}

/** The progress line's words for the time state: `ETA 14m`, `stalled`,
 *  `ended 21d ago · 180 never started`, `finished 2h ago`. */
function timeParts(j: Progress, eta: (left: string) => string): string[] {
  const when = j.finished_at ? ` ${relTime(j.finished_at)}` : "";
  const state = jobTimeState(j);
  switch (state.kind) {
    case "eta": return [eta(state.left)];
    case "stalled": return ["stalled"];
    case "ended": return [`ended${when}`, `${fmtCount(state.never)} never started`];
    case "finished": return when ? [`finished${when}`] : [];
  }
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

export const jobProgressText = (j: Progress) => joinParts(jobProgressParts(j));

/** The same, for a screen reader. */
export const jobSpoken = (j: Progress) =>
  joinParts(parts(j, `${fmtCount(j.done)} of ${fmtCount(j.expected)} runs done`, (left) => `about ${left} left`), ", ");

/** Each state's share (percent) of the expected runs (of the runs so far,
 *  once more ran than expected), like a group header's bar; the rest is
 *  the empty track. Null for a job of one run or none. */
export function jobBarSegments(j: Pick<JobProgressFields, "counts" | "expected">) {
  const c = j.counts;
  const of = Math.max(j.expected, c.running + c.waiting + c.succeeded + c.failed + c.stuck);
  return barSegments({ total: of, done: c.succeeded, failed: c.failed, stuck: c.stuck, running: c.running });
}

/** What a Jobs-view cell shows, and its tooltip. */
export interface JobCell { text: string; title?: string }

const STALLED_TITLE = "no run finished in the last 10 minutes";

/** `14m` left, `stalled`, `finished 3d ago` or `ended · 180 never started`. */
export function jobEtaCell(j: Progress): JobCell {
  const state = jobTimeState(j);
  switch (state.kind) {
    case "eta": return { text: state.left, title: `about ${state.left} left` };
    case "stalled": return { text: "stalled", title: STALLED_TITLE };
    case "ended": return { text: `ended · ${fmtCount(state.never)} never started`, title: "the job has ended" };
    case "finished": {
      const when = relTime(j.finished_at);
      return { text: when ? `finished ${when}` : "finished", title: j.finished_at ?? "the job has finished" };
    }
  }
}

/** `41/min`, else a dash saying why nothing completes. */
export function jobRateCell(j: Progress): JobCell {
  const rate = throughputText(j);
  if (rate) return { text: rate, title: "runs finished a minute, over the last 10 minutes" };
  return { text: "—", title: inFlight(j) ? STALLED_TITLE : "the job has ended" };
}
