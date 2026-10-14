/** What a group header row says (plan 22 G4, G10): its status count and,
 *  per metric, the aggregate the board shows. */
import { fmtCount, plural } from "../util";
import { joinParts } from "../util/toneParts";
import type { GroupAggregate, GroupCounts, MetricAggregate } from "../apiGroups";

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

/** The aggregate shown for *agg*: the mean for `best` of a metric without a goal. */
export const shownAggregate = (a: MetricAggregate, agg: GroupAggregate): GroupAggregate =>
  agg === "best" && a.best === null ? "mean" : agg;

/** A header's cell for one metric: *agg* of the group's values, the mean for
 *  `best` of a metric without a goal; its title names what it shows. */
export function aggregateCell(
  a: MetricAggregate | undefined, agg: GroupAggregate,
): { value: number | null; title: string | undefined } {
  if (!a || a.n === 0) return { value: null, title: undefined };
  const used = shownAggregate(a, agg);
  return { value: a[used], title: `${used} of ${a.n}${used !== agg ? " (no goal)" : ""}` };
}

/** A `+N more` row's text in each state of its load. */
export const MORE_TEXT = {
  idle: (n: number) => `+${n} more`, loading: () => "Loading…", error: () => "Could not load them, retry",
};
