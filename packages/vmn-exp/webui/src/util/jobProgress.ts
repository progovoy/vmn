/** What a job's progress says (plan 23 W1, §3.1): `1,412/2,000 · 3 failed ·
 *  41/min · ETA 14m`, and its run bar over the expected runs. An outer run
 *  that declares its own progress (plan 28 P2) leads with it instead:
 *  `41/60 dates · 1,415 runs · 3 failed · 20 dates/h · ETA 14m`, its bar
 *  that share alone. */
import type { JobProgressFields } from "../types";
import { fmtCount, humanizeSeconds, relTime } from "../util";
import { barSegments } from "../pages/groupHeaderText";
import { joinParts } from "./toneParts";

/** Whole from 10, one decimal below. */
const roundRate = (n: number) => (n >= 10 ? Math.round(n) : Math.round(n * 10) / 10);

/** `41/min`; one decimal below 10 a minute (`0.3/min`). */
export function fmtThroughput(perMin: number): string {
  return `${fmtCount(roundRate(perMin))}/min`;
}

/** ` dates` after a number, nothing without a unit. */
export const unitSuffix = (unit: string | null) => (unit ? ` ${unit}` : "");

/** A declared progress's rate in its *unit*: a minute from one a minute,
 *  an hour below (`41 dates/min`, `20 dates/h`). */
export function fmtRate(perMin: number, unit: string | null): string {
  const [n, per] = perMin >= 1 ? [perMin, "min"] : [perMin * 60, "h"];
  return `${fmtCount(roundRate(n))}${unitSuffix(unit)}/${per}`;
}

/** What a job's bar and line lead with: its declared progress (plan 28
 *  P2; *declared*: the runs then follow it), else its runs done of the expected. */
export interface ProgressLead { done: number; total: number; unit: string | null; declared: boolean }

export function progressLead(j: Pick<JobProgressFields, "done" | "expected" | "declared_progress">): ProgressLead {
  const d = j.declared_progress;
  return d ? { done: d.done, total: d.total, unit: d.unit, declared: true }
    : { done: j.done, total: j.expected, unit: null, declared: false };
}

/** The job's completions a minute (its declared progress's rate, when it
 *  declares one), null while nothing completes. */
export function throughputText(j: Pick<JobProgressFields, "throughput_per_min" | "declared_progress">) {
  const d = j.declared_progress;
  if (d) return d.rate_per_min ? fmtRate(d.rate_per_min, d.unit) : null;
  return j.throughput_per_min > 0 ? fmtThroughput(j.throughput_per_min) : null;
}

/** The time left, null when done or unknown. */
export const etaText = (j: Pick<JobProgressFields, "eta_sec">) => (j.eta_sec ? humanizeSeconds(j.eta_sec) : null);

type Progress = Pick<JobProgressFields, "counts" | "done" | "expected" | "throughput_per_min" | "eta_sec" | "finished_at" | "lost">
  & Partial<Pick<JobProgressFields, "total" | "declared_progress">>;

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

function parts(j: Progress, done: string[], eta: (left: string) => string): ProgressPart[] {
  const troubles = (["failed", "stuck"] as const)
    .filter((t) => j.counts[t] > 0).map((t): ProgressPart => ({ text: `${fmtCount(j.counts[t])} ${t}`, tone: t }));
  // Stuck under an outer run that ended: they never report, a failure.
  const lost: ProgressPart[] = j.lost ? [{ text: `${fmtCount(j.lost)} lost`, tone: "failed" }] : [];
  const rate = throughputText(j);
  return [...done.map((text) => ({ text })), ...troubles, ...lost, ...(rate ? [{ text: rate }] : []),
    ...timeParts(j, eta).map((text) => ({ text }))];
}

/** The line's lead (`41/60 dates`, then `1,415 runs`; else `1,412/2,000`). */
function doneParts(j: Progress, spoken: boolean): string[] {
  const l = progressLead(j);
  const lead = spoken
    ? `${fmtCount(l.done)} of ${fmtCount(l.total)}${unitSuffix(l.declared ? l.unit : "runs")} done`
    : `${fmtCount(l.done)}/${fmtCount(l.total)}${unitSuffix(l.unit)}`;
  return l.declared ? [lead, `${fmtCount(j.total ?? j.done)} runs`] : [lead];
}

/** The progress line's parts, failed and stuck toned (the job header's). */
export const jobProgressParts = (j: Progress) => parts(j, doneParts(j, false), (left) => `ETA ${left}`);

export const jobProgressText = (j: Progress) => joinParts(jobProgressParts(j));

/** The same, for a screen reader. */
export const jobSpoken = (j: Progress) => joinParts(parts(j, doneParts(j, true), (left) => `about ${left} left`), ", ");

/** Each state's share (percent) of the expected runs (of the runs so far,
 *  once more ran than expected), like a group header's bar; the rest is
 *  the empty track — waiting, or never started once the outer run ended,
 *  whose lost runs fill the failed share. A declared progress fills its
 *  own share alone. Null for a job of one run or none. */
export function jobBarSegments(j: Pick<JobProgressFields, "counts" | "done" | "expected" | "never_started" | "lost" | "declared_progress">) {
  const l = progressLead(j);
  if (l.declared) return barSegments({ total: l.total, done: Math.min(l.done, l.total), failed: 0, stuck: 0, running: 0 });
  const c = j.counts;
  const lost = j.lost ?? 0;
  const runs = c.running + c.waiting + c.succeeded + c.failed + c.stuck + lost + (j.never_started ?? 0);
  const of = Math.max(j.expected, runs);
  return barSegments({ total: of, done: c.succeeded, failed: c.failed + lost, stuck: c.stuck, running: c.running });
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
    case "ended": return { text: `ended · ${fmtCount(state.never)} never started`, title: "the outer run has ended" };
    case "finished": {
      const when = relTime(j.finished_at);
      return { text: when ? `finished ${when}` : "finished", title: j.finished_at ?? "the outer run has finished" };
    }
  }
}

/** `41/min` (a declared progress's `20 dates/h`), else a dash saying why nothing completes. */
export function jobRateCell(j: Progress): JobCell {
  const rate = throughputText(j);
  const d = j.declared_progress;
  if (rate && d) return { text: rate, title: `${d.unit ?? "progress"} done since the outer run started` };
  if (rate) return { text: rate, title: "runs finished a minute, over the last 10 minutes" };
  return { text: "—", title: inFlight(j) ? STALLED_TITLE : "the outer run has ended" };
}
