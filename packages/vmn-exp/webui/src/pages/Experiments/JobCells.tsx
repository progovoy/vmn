/** What a Jobs-view row and card show (plan 23 W1, §3.1): a job's progress
 *  or a single run's base, and its best value with the inner
 *  run it comes from. */
import { Link } from "react-router-dom";
import type { BaselineChipEntry } from "../../apiBaseline";
import BaselineChip from "../../components/BaselineChip";
import JobProgress from "../../components/JobProgress";
import Sparkline from "../../components/Sparkline";
import type { AttentionEntry } from "../../shell/contracts";
import type { ExperimentRow } from "../../types";
import { fmtCount, fmtPct, fmtVal, runHref } from "../../util";
import type { SearchFilter } from "../../util/searchScope";
import { jobEtaCell, jobRateCell, type JobCell } from "../../util/jobProgress";

export interface JobContext {
  runBase: string;
  /** The Best column's metric, and the way it improves. */
  metric: string | null;
  goal: "min" | "max" | null;
  /** The search every run is matched by (plan 23 W11), for the job chips. */
  search?: SearchFilter | null;
  /** The app's attention queries (plan 28 P1): labels and levels of `job.attention`. */
  attention?: readonly AttentionEntry[];
  /** Each outer run's baseline chip (plan 28 N3), by verstr; null: none. */
  baselines?: Readonly<Record<string, BaselineChipEntry | null>>;
}

/** An outer run's baseline chip, opening its Overview (where the comparison is). */
export function BaselineCell({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  const chip = ctx.baselines?.[r.verstr];
  if (!chip) return null;
  return <BaselineChip chip={chip} baseline={chip.baseline} href={`${runHref(ctx.runBase, r.verstr)}?tab=overview`} />;
}

/** An outer run's non-zero attention counts, `2 unstable`, in config order. */
export function AttentionChips({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  const counts = r.job?.attention;
  const shown = counts ? (ctx.attention ?? []).filter((e) => (counts[e.key] ?? 0) > 0) : [];
  if (!shown.length) return null;
  return (
    <span className="job-attention">
      {shown.map((e) => <AttentionChip key={e.key} entry={e} count={counts![e.key]} />)}
    </span>
  );
}

/** One attention part's chip, `2 unstable`, coloured by its level. */
export function AttentionChip({ entry, count }: { entry: AttentionEntry; count: number }) {
  return (
    <span className={`job-attention-chip attention-${entry.level}`} title={entry.q}>
      {`${fmtCount(count)} ${entry.label}`}
    </span>
  );
}

/** Under the name: a job's progress, a single run's base (its branch is the
 *  Branch column's). */
export function JobSubLine({ r, inline = false }: { r: ExperimentRow; inline?: boolean }) {
  if (r.job) return <JobProgress job={r.job} inline={inline} />;
  return <span className="job-sub mono">{r.base_version}</span>;
}

const arrow = (goal: JobContext["goal"]) => (goal === "min" ? "↓" : goal === "max" ? "↑" : "");

/** A job's best run on the metric (its `@N` linked), a single run's own
 *  value; a dash for a job whose runs have the metric but no best (no goal
 *  declared: the server ranks nothing). */
export function BestValue({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  const j = r.job;
  const value = j ? j.best : ctx.metric ? r.metrics[ctx.metric] : null;
  if (value == null) {
    if (!j?.metric || !j.spread?.some(Boolean)) return null;
    return <span className="job-best muted" title={`no goal declared for ${j.metric} — not ranked`}>—</span>;
  }
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

export type JobNumber = "runs" | "failed" | "throughput" | "eta";
const EMPTY: JobCell = { text: "" };

/** A job's number columns, with a tooltip where the text needs one; empty
 *  for a single run. */
export function jobNumbers(r: ExperimentRow): Record<JobNumber, JobCell> {
  const j = r.job;
  if (!j) return { runs: EMPTY, failed: EMPTY, throughput: EMPTY, eta: EMPTY };
  return {
    runs: { text: fmtCount(j.total) }, failed: { text: fmtPct(j.failed_pct) },
    throughput: jobRateCell(j), eta: jobEtaCell(j),
  };
}
