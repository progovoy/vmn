/** What a group header row says (plan 22 G4, G10): its status count and,
 *  per metric, the aggregate the board shows. */
import { NO_GOAL, fmtCount, fmtVal, noGoalTitle, plural } from "../util";
import { joinParts } from "../util/toneParts";
import type { GroupAggregate, GroupCounts, MetricAggregate } from "../apiGroups";
import type { JobAggChoice } from "../types";
import { mixText, withMix } from "../util/metricPolicy";
import { possessive, rolledBasis, tailLabel } from "../util/jobAggregate";

export type CountTone = "total" | "running" | "waiting" | "stuck" | "failed" | "done";

/** The states a header names besides the total; done is the rest. */
const NAMED: readonly Exclude<CountTone, "total" | "done">[] = ["running", "waiting", "stuck", "failed"];

const isCut = (total: number, unfiltered: number | undefined) =>
  unfiltered !== undefined && unfiltered !== total;

/** `16 runs`, `1 run`, or `5 of 16 runs` when the filters leave *total* of
 *  the group's *unfiltered* runs (plan 22 F1). */
export const sizeText = (c: GroupCounts, unfiltered?: number): string =>
  isCut(c.total, unfiltered) ? `${fmtCount(c.total)} of ${plural(unfiltered!, "run")}` : plural(c.total, "run");

/** The total in words, then each state that is not done and has runs; a
 *  group with none of those reads `all succeeded` (plan 22 F2), or names
 *  the count when the filters cut the group (`5 of 16 runs · 5 succeeded`). */
export function countParts(c: GroupCounts, unfiltered?: number): { text: string; tone: CountTone }[] {
  const named = NAMED.filter((t) => c[t] > 0).map((t) => ({ text: `${fmtCount(c[t])} ${t}`, tone: t }));
  const done = isCut(c.total, unfiltered) ? `${fmtCount(c.done)} succeeded` : "all succeeded";
  const rest = named.length || c.total === 0 ? named : [{ text: done, tone: "done" as const }];
  return [{ text: sizeText(c, unfiltered), tone: "total" }, ...rest];
}

/** `16 runs · 2 running · 1 failed`. */
export const countsText = (c: GroupCounts, unfiltered?: number) =>
  joinParts(countParts(c, unfiltered));

/** `16 runs, 2 running, 1 failed`, for a screen reader. */
export const spokenCounts = (c: GroupCounts, unfiltered?: number) =>
  joinParts(countParts(c, unfiltered), ", ");

/** The states a group's run bar fills, left to right: the finished runs,
 *  then the running; the waiting ones are the empty track. */
const BAR: readonly Exclude<CountTone, "total" | "waiting">[] = ["done", "failed", "stuck", "running"];

/** A group header's run bar (plan 22 F13), each state's share of the runs
 *  in percent; null for a group of one run or none, which needs no bar. */
export function barSegments(c: Omit<GroupCounts, "waiting">): { tone: CountTone; pct: number }[] | null {
  if (c.total <= 1) return null;
  return BAR.filter((t) => c[t] > 0).map((t) => ({ tone: t, pct: Math.round((c[t] / c.total) * 10000) / 100 }));
}

const FOLLOWS_GOAL: readonly GroupAggregate[] = ["best", "best10", "worst10"];

/** `best` or a tail of a metric without a goal: it has none (plan 32 F6). */
export const noGoalBest = (a: MetricAggregate, agg: GroupAggregate) => FOLLOWS_GOAL.includes(agg) && !a.goal;

/** The aggregate's name as a header shows it: `best (no goal)` without a
 *  goal, a tail with its percentile, `best10 (p90)`. */
export const aggregateName = (a: MetricAggregate, agg: GroupAggregate) =>
  `${tailLabel(agg, a.goal)}${noGoalBest(a, agg) ? NO_GOAL : ""}`;

/** A header's cell for one metric: *agg* of the group's values (`best` of a
 *  metric without a goal has none, never another aggregate); its title
 *  names what it shows, and the runs overriding the schema's summary policy
 *  (plan 32 F1). */
export function aggregateCell(
  a: MetricAggregate | undefined, agg: GroupAggregate,
): { value: number | null; title: string | undefined } {
  if (!a || a.n === 0) return { value: null, title: undefined };
  return { value: a[agg] ?? null, title: withMix(`${tailLabel(agg, a.goal)} of ${a.n}${noGoalBest(a, agg) ? NO_GOAL : ""}`, a.policies) };
}

/** A grouped Outer runs header's value (plan 31 §2): *agg* of the group's
 *  outer runs' *rolled* values, `median 0.65` titled `median of 12 outer
 *  runs' median of dates' own date.best_value`; `— (no goal)` without a
 *  goal, `—` when none of them has a value (plan 32). */
export function jobGroupCell(a: MetricAggregate | undefined, agg: GroupAggregate, rolled: JobAggChoice): {
  name: string | null; value: string; noGoal: boolean; mix: string | null; title: string;
} {
  const goal = a?.goal ?? rolled.goal;
  if (!goal) return { name: null, value: "—", noGoal: true, mix: null, title: noGoalTitle(rolled.metric) };
  const value = a?.[agg];
  if (!a || a.n === 0 || value == null) {
    return { name: null, value: "—", noGoal: false, mix: null, title: `no outer run of the group has a ${rolled.metric}` };
  }
  const name = tailLabel(agg, goal);
  const mix = mixText(a.policies ?? null);
  const title = `${name} of ${possessive(plural(a.n, "outer run"))} ${rolledBasis(rolled)}`;
  return { name, value: fmtVal(value), noGoal: false, mix, title: mix ? `${title} · ${mix}` : title };
}

/** A `+N more` row's text in each state of its load. */
export const MORE_TEXT = {
  idle: (n: number) => `+${n} more`, loading: () => "Loading…", error: () => "Could not load them, retry",
};
