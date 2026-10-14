/** What a Jobs-view row and card show (plan 23 W1, §3.1): a job's progress
 *  or a single run's base, and its best value with the inner
 *  run it comes from. */
import { Link } from "react-router-dom";
import JobProgress from "../../components/JobProgress";
import Sparkline from "../../components/Sparkline";
import type { ExperimentRow } from "../../types";
import { fmtCount, fmtVal, runHref } from "../../util";
import type { SearchFilter } from "../../util/searchScope";
import { jobEtaCell, jobRateCell, type JobCell } from "../../util/jobProgress";

export interface JobContext {
  runBase: string;
  /** The Best column's metric, and the way it improves. */
  metric: string | null;
  goal: "min" | "max" | null;
  /** The search every run is matched by (plan 23 W11), for the job chips. */
  search?: SearchFilter | null;
}

/** Under the name: a job's progress, a single run's base (its branch is the
 *  Branch column's). */
export function JobSubLine({ r }: { r: ExperimentRow }) {
  if (r.job) return <JobProgress job={r.job} />;
  return <span className="job-sub mono">{r.base_version}</span>;
}

const arrow = (goal: JobContext["goal"]) => (goal === "min" ? "↓" : goal === "max" ? "↑" : "");

/** A job's best run on the metric (its `@N` linked), a single run's own value. */
export function BestValue({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  const j = r.job;
  const value = j ? j.best : ctx.metric ? r.metrics[ctx.metric] : null;
  if (value == null) return null;
  const metric = j?.metric ?? ctx.metric;
  const goal = arrow(ctx.goal);
  return (
    <span className="job-best" title={metric ? `best ${metric}` : undefined}>
      <span className="metric">{fmtVal(value)}</span>
      {goal && <span className="goal"> {goal}</span>}
      {j?.best_verstr && (
        <Link className="job-best-run mono" to={runHref(ctx.runBase, j.best_verstr)} title={j.best_verstr}>
          {j.best_idx != null ? `@${j.best_idx}` : j.best_verstr}
        </Link>
      )}
    </span>
  );
}

export function SpreadCell({ r }: { r: ExperimentRow }) {
  const j = r.job;
  if (!j?.spread?.length || !j.metric) return null;
  const n = j.spread.reduce((a, b) => a + b, 0);
  return <Sparkline counts={j.spread} title={`distribution of ${j.metric} over ${fmtCount(n)} runs`} />;
}

const pct = (v: number) => `${v >= 10 || v === 0 ? Math.round(v) : Math.round(v * 10) / 10}%`;

/** A job's number columns, with a tooltip where the text needs one; empty
 *  for a single run. */
export function jobNumbers(r: ExperimentRow): Record<"runs" | "failed" | "throughput" | "eta", JobCell | string> {
  const j = r.job;
  if (!j) return { runs: "", failed: "", throughput: "", eta: "" };
  return { runs: fmtCount(j.total), failed: pct(j.failed_pct), throughput: jobRateCell(j), eta: jobEtaCell(j) };
}
