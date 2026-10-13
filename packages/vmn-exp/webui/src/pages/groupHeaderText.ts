/** What a group header row says (plan 22 G4, G10): its status count and,
 *  per metric, the aggregate the board shows. */
import { plural } from "../util";
import type { GroupAggregate, GroupCounts, MetricAggregate } from "../apiGroups";

export type CountTone = "total" | "running" | "waiting" | "stuck" | "failed" | "done";

/** The states a header names besides the total; done is the rest. */
const NAMED: readonly Exclude<CountTone, "total" | "done">[] = ["running", "waiting", "stuck", "failed"];

/** `16 runs`, `1 run`, or `5 of 16 runs` when the filters leave *of* of the
 *  group's *unfiltered* runs (plan 22 F1). */
function totalText(total: number, unfiltered: number | undefined): string {
  return unfiltered === undefined || unfiltered === total
    ? plural(total, "run")
    : `${total} of ${plural(unfiltered, "run")}`;
}

/** The total in words, then each state that is not done and has runs; a
 *  group with none of those reads `all succeeded` (plan 22 F2). */
export function countParts(c: GroupCounts, unfiltered?: number): { text: string; tone: CountTone }[] {
  const named = NAMED.filter((t) => c[t] > 0).map((t) => ({ text: `${c[t]} ${t}`, tone: t }));
  const rest = named.length || c.total === 0 ? named : [{ text: "all succeeded", tone: "done" as const }];
  return [{ text: totalText(c.total, unfiltered), tone: "total" }, ...rest];
}

/** `16 runs · 2 running · 1 failed`. */
export const countsText = (c: GroupCounts, unfiltered?: number) =>
  countParts(c, unfiltered).map((p) => p.text).join(" · ");

/** `16 runs, 2 running, 1 failed`, for a screen reader. */
export const spokenCounts = (c: GroupCounts, unfiltered?: number) =>
  countParts(c, unfiltered).map((p) => p.text).join(", ");

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
