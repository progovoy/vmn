/** The time a Jobs-view row and card show (plan 32 F14): a job's `when_at`,
 *  the one `job:started` sorts on, else a single run's start; `created`
 *  when that time is the creation of a run that never started. */
import type { ExperimentRow } from "../types";
import { relTime } from "../util";

export interface JobWhen { at: string | null; created: boolean }

export function jobWhen(r: Pick<ExperimentRow, "job" | "started_at" | "timestamp">): JobWhen {
  const j = r.job;
  if (j) return { at: j.when_at ?? null, created: j.when_source === "created" };
  return r.started_at ? { at: r.started_at, created: false } : { at: r.timestamp, created: true };
}

/** `3h ago`, `created 3h ago`. */
export function jobWhenText(w: JobWhen): string {
  if (!w.at) return "";
  return w.created ? `created ${relTime(w.at)}` : relTime(w.at);
}

/** `started <iso>`, `created <iso>`. */
export const jobWhenTitle = (w: JobWhen) => (w.at ? `${w.created ? "created" : "started"} ${w.at}` : undefined);
