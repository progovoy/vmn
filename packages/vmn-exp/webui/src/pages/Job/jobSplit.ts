/** The Overview's split table (plan 28 P3): per value of the summary's
 *  split field, its counts and durations, each a link to the job's Runs
 *  tab filtered by the value's clause (and the count's statuses). Pure. */
import type { JobSplitEntry } from "../../apiJob";
import { fmtCount, fmtDuration } from "../../util";
import { failedCount } from "./jobData";
import { jobTabHref } from "./jobQueries";

export interface SplitCell {
  text: string;
  /** What a screen reader says of the link, when it is not the text. */
  label?: string;
  href?: string;
}

const COUNTS: { name: string; status: string | null; of: (e: JobSplitEntry) => number }[] = [
  { name: "runs", status: null, of: (e) => e.total },
  { name: "done", status: "succeeded,failed", of: (e) => e.done },
  { name: "failed", status: "failed,stuck", of: failedCount },
  { name: "running", status: "running", of: (e) => e.counts.running },
  { name: "waiting", status: "created", of: (e) => e.counts.waiting },
];

export const SPLIT_COLUMNS = [...COUNTS.map((c) => c.name), "p50", "p90"];

function href(runBase: string, clause: string | null, status: string | null) {
  if (!clause) return undefined;
  return jobTabHref(runBase, "runs", status ? { q: clause, status } : { q: clause });
}

/** The value's cell, then one per :data:`SPLIT_COLUMNS`. */
export function splitCells(entry: JobSplitEntry, runBase: string): SplitCell[] {
  const counts = COUNTS.map(({ name, status, of }): SplitCell => {
    const n = of(entry);
    return {
      text: fmtCount(n), href: href(runBase, entry.clause, status),
      label: `${fmtCount(n)} ${entry.label} runs${name === "runs" ? "" : ` ${name}`}`,
    };
  });
  return [
    { text: entry.label, href: href(runBase, entry.clause, null) },
    ...counts,
    { text: fmtDuration(entry.duration.p50) },
    { text: fmtDuration(entry.duration.p90) },
  ];
}
