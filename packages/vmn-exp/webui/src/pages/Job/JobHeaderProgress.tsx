/** The job header's progress (plan 23 §3.2): a full-width run bar in the
 *  status colours (finished from the left, the waiting runs the empty
 *  track), the counts line under it. Its words are the Jobs view's
 *  (util/jobProgress), the failed and stuck runs counted apart. */
import type { JobPageSummary } from "../../apiJob";
import SegmentBar from "../../components/SegmentBar";
import ToneParts from "../../components/ToneParts";
import { jobBarSegments, jobProgressParts, jobSpoken } from "../../util/jobProgress";

export default function JobHeaderProgress({ summary }: { summary: JobPageSummary }) {
  const segments = jobBarSegments(summary) ?? [];
  return (
    <div className="job-head-progress">
      <SegmentBar
        className="job-head-bar" segments={segments} role="progressbar" aria-label={jobSpoken(summary)}
        aria-valuemin={0} aria-valuemax={summary.expected} aria-valuenow={summary.done}
      />
      <ToneParts className="job-head-counts" parts={jobProgressParts(summary)} />
    </div>
  );
}
