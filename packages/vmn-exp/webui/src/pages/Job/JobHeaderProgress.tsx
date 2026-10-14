/** The job header's progress (plan 23 §3.2): a full-width run bar in the
 *  status colours (finished from the left, the waiting runs the empty
 *  track), the counts line under it. Its words are the Jobs view's
 *  (util/jobProgress), the failed and stuck runs counted apart. */
import { Fragment } from "react";
import type { JobSummary } from "../../apiJob";
import { jobBarSegments, jobProgressParts, jobSpoken } from "../../util/jobProgress";

export default function JobHeaderProgress({ summary }: { summary: JobSummary }) {
  const segments = jobBarSegments(summary) ?? [];
  const parts = jobProgressParts(summary);
  return (
    <div className="job-head-progress">
      <span
        className="job-head-bar" role="progressbar" aria-label={jobSpoken(summary)}
        aria-valuemin={0} aria-valuemax={summary.expected} aria-valuenow={summary.done}
      >
        {segments.map((sg) => (
          <span key={sg.tone} className={`group-bar-seg tone-${sg.tone}`} data-tone={sg.tone} style={{ width: `${sg.pct}%` }} />
        ))}
      </span>
      <span className="job-head-counts">
        {parts.map((p, i) => (
          <Fragment key={i}>
            {i > 0 && <span aria-hidden="true"> · </span>}
            <span className={p.tone && `tone-${p.tone}`}>{p.text}</span>
          </Fragment>
        ))}
      </span>
    </div>
  );
}
