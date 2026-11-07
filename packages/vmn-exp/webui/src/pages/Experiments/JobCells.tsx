/** What a Jobs-view row and card show (plan 23 W1, §3.1): a job's progress
 *  or a single run's base, and its value (the board's aggregate, plan 31
 *  §2) with the run holding it. */
import { Link } from "react-router-dom";
import type { BaselineChipEntry } from "../../apiBaseline";
import BaselineChip from "../../components/BaselineChip";
import JobProgress from "../../components/JobProgress";
import PolicyMixMark from "../../components/PolicyMixMark";
import Sparkline from "../../components/Sparkline";
import type { AttentionEntry } from "../../shell/contracts";
import type { ExperimentRow, JobRolled, PolicyMix } from "../../types";
import { NO_GOAL, fmtCount, fmtPct, fmtVal, noGoalTitle, runHref } from "../../util";
import type { SearchFilter } from "../../util/searchScope";
import { jobEtaCell, jobRateCell, jobThroughputCell, type JobCell } from "../../util/jobProgress";
import { rolledTitle, rolledValueText } from "../../util/jobAggregate";
import { mixText, withMix } from "../../util/metricPolicy";

export interface JobContext {
  runBase: string;
  /** The page's main metric (a single run's value), and the way it improves. */
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

/** The value column: a job's chosen aggregate (`rolled`, plan 31 §2; none
 *  without one, never its best instead), a single run's own main metric. */
export function ValueCell({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  if (!r.job) return <BestValue r={r} ctx={ctx} />;
  const { rolled } = r.job;
  if (!rolled) return null;
  // The rollup's policy mix is of the main metric's runs: only its own aggregate's.
  return <RolledValue r={rolled} ctx={ctx} policies={rolled.metric === r.job.metric ? r.job.policies : undefined} />;
}

/** The value (linked to the unit holding it, `≈` when approximate, the
 *  arrow its goal), titled by its aggregate, coverage and source; `— (no
 *  goal)` without a goal (the server ranks nothing), `—` with no unit. */
function RolledValue({ r, ctx, policies }: { r: JobRolled; ctx: JobContext; policies?: PolicyMix["policies"] }) {
  const title = withMix(rolledTitle(r), policies);
  if (r.value == null) {
    return (
      <span className="job-best">
        <span className="muted" title={title}>—</span>
        {!r.goal && <span className="goal">{NO_GOAL}</span>}
      </span>
    );
  }
  const text = rolledValueText(r);
  const goal = arrow(r.goal);
  return (
    <span className="job-best" title={title}>
      {r.verstr
        ? <Link className="metric" to={runHref(ctx.runBase, r.verstr)}>{text}</Link>
        : <span className="metric">{text}</span>}
      <PolicyMixMark text={mixText(policies)} />
      {goal && <span className="goal"> {goal}</span>}
    </span>
  );
}

/** A tree row's best run on the metric (its `@N` linked, the arrow its
 *  rollup's goal: a tree row keeps its own values, plan 31 §2), a single
 *  run's own value; `— (no goal)` for a job whose runs have the metric but
 *  no best (no goal declared: the server ranks nothing). */
export function BestValue({ r, ctx }: { r: ExperimentRow; ctx: JobContext }) {
  const j = r.job;
  const value = j ? j.best : ctx.metric ? r.metrics[ctx.metric] : null;
  if (value == null) {
    if (!j?.metric || j.goal !== null || !j.spread?.some(Boolean)) return null;
    return (
      <span className="job-best">
        <span className="muted" title={noGoalTitle(j.metric)}>—</span>
        <span className="goal">{NO_GOAL}</span>
      </span>
    );
  }
  const metric = j?.metric ?? ctx.metric;
  const goal = arrow(j ? j.goal : ctx.goal);
  return (
    <span className="job-best" title={metric ? withMix(`best ${metric}`, j?.policies) : undefined}>
      <span className="metric">{fmtVal(value)}</span>
      <PolicyMixMark text={mixText(j?.policies)} />
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

export type JobNumber = "runs" | "failed" | "rate" | "throughput" | "eta";
const EMPTY: JobCell = { text: "" };

/** A job's number columns, with a tooltip where the text needs one; empty
 *  for a single run. */
export function jobNumbers(r: ExperimentRow): Record<JobNumber, JobCell> {
  const j = r.job;
  if (!j) return { runs: EMPTY, failed: EMPTY, rate: EMPTY, throughput: EMPTY, eta: EMPTY };
  return {
    runs: { text: fmtCount(j.total) }, failed: { text: fmtPct(j.failed_pct) },
    rate: jobRateCell(j), throughput: jobThroughputCell(j), eta: jobEtaCell(j),
  };
}
