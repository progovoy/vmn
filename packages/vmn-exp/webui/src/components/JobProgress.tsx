/** A job's progress (plan 23 W1): its run bar (finished runs from the left,
 *  the waiting and not yet launched ones the empty track) and the line
 *  `1,412/2,000 · 3 failed · 41/min · ETA 14m`. Shared by the Jobs view's
 *  rows and cards, and the job page's header. */
import type { JobSummary } from "../types";
import { jobBarSegments, jobProgressText, jobSpoken } from "../util/jobProgress";
import "./jobProgress.css";

export default function JobProgress({ job }: { job: JobSummary }) {
  const segments = jobBarSegments(job);
  const text = jobProgressText(job);
  return (
    <span className="job-progress" title={text}>
      {segments && (
        <span className="job-bar" aria-hidden="true">
          {segments.map((sg) => (
            <span key={sg.tone} className={`job-bar-seg tone-${sg.tone}`} style={{ width: `${sg.pct}%` }} />
          ))}
        </span>
      )}
      <span className="job-progress-text" aria-hidden="true">{text}</span>
      <span className="sr-only">{jobSpoken(job)}</span>
    </span>
  );
}
