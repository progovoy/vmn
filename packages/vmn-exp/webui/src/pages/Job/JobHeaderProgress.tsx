/** The job header's progress (plan 23 §3.2): a full-width run bar in the
 *  status colours (finished from the left, the waiting runs the empty
 *  track; a declared progress's share, plan 28 P2), the counts line under
 *  it. Its words are the Jobs view's (util/jobProgress), the failed and
 *  stuck runs counted apart. */
import SegmentBar from "../../components/SegmentBar";
import ToneParts from "../../components/ToneParts";
import type { JobProgressFields } from "../../types";
import { jobBarSegments, jobProgressParts, jobSpoken, progressLead } from "../../util/jobProgress";

export default function JobHeaderProgress({ summary }: { summary: JobProgressFields }) {
  const segments = jobBarSegments(summary) ?? [];
  const lead = progressLead(summary);
  return (
    <div className="job-head-progress">
      <SegmentBar
        className="job-head-bar" segments={segments} role="progressbar" aria-label={jobSpoken(summary)}
        aria-valuemin={0} aria-valuemax={lead.total} aria-valuenow={lead.done}
      />
      <ToneParts className="job-head-counts" parts={jobProgressParts(summary)} />
    </div>
  );
}
