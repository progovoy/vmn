/** The job header's progress (plan 23 §3.2): the run bar in the status
 *  colours (finished from the left, the waiting runs the empty track, as
 *  F13's group bar), `done/expected`, the failures, throughput and ETA.
 *  Same semantics as the Jobs view's JobProgress; to be merged with it. */
import { Fragment } from "react";
import type { JobSummary } from "../../apiJob";
import type { GroupCounts } from "../../apiGroups";
import { fmtCount, plural } from "../../util";
import { barSegments } from "../groupHeaderText";
import { etaText, failedCount, throughputText } from "./jobData";

/** The job's counts over its expected size, the shape the group bar reads. */
export function barCounts(s: Pick<JobSummary, "counts" | "expected" | "total">): GroupCounts {
  const c = s.counts;
  const total = Math.max(s.expected, s.total);
  return {
    total, running: c.running, failed: c.failed, stuck: c.stuck, done: c.succeeded,
    waiting: total - c.running - c.failed - c.stuck - c.succeeded,
  };
}

export default function JobHeaderProgress({ summary }: { summary: JobSummary }) {
  const segments = barSegments(barCounts(summary)) ?? [];
  const failed = failedCount(summary);
  const parts = [
    { text: `${fmtCount(summary.done)}/${fmtCount(summary.expected)}` },
    { text: failed ? `${fmtCount(failed)} failed` : null, tone: "tone-failed" },
    { text: throughputText(summary.throughput_per_min) },
    { text: etaText(summary.eta_sec, summary.expected - summary.done) },
  ].filter((p) => p.text);
  const spoken = `${plural(summary.done, "run")} done of ${fmtCount(summary.expected)}`
    + `${failed ? `, ${fmtCount(failed)} failed` : ""}, ${fmtCount(summary.counts.running)} running`;
  return (
    <div className="job-progress">
      <span
        className="job-bar" role="progressbar" aria-label={spoken}
        aria-valuemin={0} aria-valuemax={summary.expected} aria-valuenow={summary.done}
      >
        {segments.map((sg) => (
          <span key={sg.tone} className={`group-bar-seg tone-${sg.tone}`} data-tone={sg.tone} style={{ width: `${sg.pct}%` }} />
        ))}
      </span>
      <span className="job-progress-text">
        {parts.map((p, i) => (
          <Fragment key={i}>
            {i > 0 && <span aria-hidden="true"> · </span>}
            <span className={p.tone}>{p.text}</span>
          </Fragment>
        ))}
      </span>
    </div>
  );
}
