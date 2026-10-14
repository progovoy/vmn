/** A job's progress (plan 23 W1): its run bar (finished runs from the left,
 *  the waiting and not yet launched ones the empty track) and the line
 *  `1,412/2,000 · 3 failed · 41/min · ETA 14m` below it (*inline*: beside it,
 *  for a compact row). Shared by the Jobs view's rows and cards. */
import type { JobRollup } from "../types";
import SegmentBar from "./SegmentBar";
import { jobBarSegments, jobProgressText, jobSpoken } from "../util/jobProgress";
import "./jobProgress.css";

export default function JobProgress({ job, inline = false }: { job: JobRollup; inline?: boolean }) {
  const segments = jobBarSegments(job);
  const text = jobProgressText(job);
  return (
    <span className={inline ? "job-progress" : "job-progress stacked"} title={text}>
      {segments && <SegmentBar className="job-bar" segments={segments} aria-hidden="true" />}
      <span className="job-progress-text" aria-hidden="true">{text}</span>
      <span className="sr-only">{jobSpoken(job)}</span>
    </span>
  );
}
