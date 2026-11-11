/** An Outer runs row's chosen aggregate (plan 31 §2) as the web names it:
 *  the URL's `job_agg*` values, the value column's header, a cell's title
 *  and the label of its KPI tile and baseline row. Every text names the
 *  aggregate's source and coverage, and never a direction without a goal
 *  (plan 32). */
import type { JobAggChoice, JobAggregate, JobAggSource, JobRolled } from "../types";
import { fmtCount, fmtVal, noGoalTitle, type Goal } from "../util";
import { parseAggregate } from "./groupBy";

export const JOB_AGG_SOURCES: readonly JobAggSource[] = ["best", "own"];
const BY = /^(children|runs|field:(params|tags)\..+|kind:.+)$/;

/** The URL's job_agg values; null: the app's default. */
export interface JobAggParams {
  agg: JobAggregate | null;
  by: string | null;
  value: JobAggSource | null;
  metric: string | null;
  /** Carriers at any depth (plan 36 §2); undefined: the app's default. */
  nested?: boolean;
}
export type JobAggPart = keyof JobAggParams;

export const JOB_AGG_PARAMS: Readonly<Record<JobAggPart, string>> = {
  agg: "job_agg", by: "job_agg_by", value: "job_agg_value", metric: "job_agg_metric",
  nested: "job_agg_nested",
};

const NESTED: Readonly<Record<string, boolean>> = { 1: true, 0: false };

/** The job_agg values of *params* the server takes, the rest null. */
export function parseJobAgg(params: URLSearchParams): JobAggParams {
  const by = params.get(JOB_AGG_PARAMS.by);
  return {
    agg: parseAggregate(params.get(JOB_AGG_PARAMS.agg)),
    by: by && BY.test(by) ? by : null,
    value: JOB_AGG_SOURCES.find((v) => v === params.get(JOB_AGG_PARAMS.value)) ?? null,
    metric: params.get(JOB_AGG_PARAMS.metric) || null,
    nested: NESTED[params.get(JOB_AGG_PARAMS.nested) ?? ""],
  };
}

const TAIL_QUANTILE: Partial<Record<string, "best" | "worst">> = { best10: "best", worst10: "worst" };

/** `best10 (p90)`: a tail names the percentile *goal* points at (a lower-is-
 *  better metric's best10 is its p10); none without a goal. */
export function tailLabel(agg: string, goal: Goal): string {
  const tail = TAIL_QUANTILE[agg];
  if (!tail || !goal) return agg;
  return `${agg} (${(tail === "best") === (goal === "max") ? "p90" : "p10"})`;
}

const pluralNoun = (word: string) => (word.endsWith("s") ? word : `${word}s`);

/** The units *by* names, `date`/`dates` for `field:params.trade_date` (the
 *  field's last word) or `kind:date`. */
export function unitNouns(by: string): { one: string; many: string } {
  if (by === "children") return { one: "child", many: "children" };
  if (by === "runs") return { one: "run", many: "runs" };
  const name = by.slice(by.indexOf(":") + 1);
  const one = name.split(/[._]/).pop() || name;
  return { one, many: pluralNoun(one) };
}

const possessive = (many: string) => (many.endsWith("s") ? `${many}'` : `${many}'s`);
/** The aggregate with the percentile the server named (`best10 (p90)`). */
const aggName = (r: JobAggChoice) => (r.percentile ? `${r.agg} (${r.percentile})` : r.agg);

/** The value column's header: `median · dates`. */
export const rolledHeader = (r: JobAggChoice) => `${aggName(r)} · ${unitNouns(r.by).many}`;

/** A KPI tile's and a baseline row's label: `median date.best_value · dates`. */
export const rolledLabel = (r: JobAggChoice) => `${aggName(r)} ${r.metric} · ${unitNouns(r.by).many}`;

/** `14/16`, or `16` when every unit has a value. */
export const coverageCount = (r: JobRolled) => (r.n === r.of ? fmtCount(r.of) : `${fmtCount(r.n)}/${fmtCount(r.of)}`);

/** `of 14/16 dates'` (`of 9 runs'`). */
const ofUnits = (r: JobRolled) => `of ${coverageCount(r)} ${possessive(unitNouns(r.by).many)}`;

/** `of 14/16 dates' own` (`of 9 runs`: every run is its own unit, no source). */
export const coverageText = (r: JobRolled): string =>
  r.by === "runs" ? `of ${coverageCount(r)} runs` : `${ofUnits(r)} ${r.source}`;

/** The value as shown, `≈ 0.65` for an approximate quantile, `—` without one. */
export const rolledValueText = (r: JobRolled) =>
  r.value == null ? "—" : `${r.approx ? "≈ " : ""}${fmtVal(r.value)}`;

/** Whether *by*'s units are the runs carrying a field (`field:`/`kind:`). */
export const carriedBy = (by: string | null) => !!by && by !== "children" && by !== "runs";

/** ` · 3 nested under another date, not counted`, or ` · nested dates
 *  counted` (plan 36 §2); nothing for other units or none left out. */
function nestedText(r: JobRolled, one: string, many: string): string {
  if (r.nested) return ` · nested ${many} counted`;
  return r.nested_skipped ? ` · ${fmtCount(r.nested_skipped)} nested under another ${one}, not counted` : "";
}

/** A value cell's title: `median of 14/16 dates' own date.best_value · 1
 *  duplicate date left out`, `≈` first for an approximate quantile. */
export function rolledTitle(r: JobRolled): string {
  if (!r.goal) return noGoalTitle(r.metric);
  const { one, many } = unitNouns(r.by);
  const of = r.by === "runs" ? ofUnits(r) : coverageText(r);
  const dupes = r.conflicts ? ` · ${fmtCount(r.conflicts)} duplicate ${r.conflicts === 1 ? one : many} left out` : "";
  return `${r.approx ? "≈ " : ""}${aggName(r)} ${of} ${r.metric}${dupes}${nestedText(r, one, many)}`;
}
