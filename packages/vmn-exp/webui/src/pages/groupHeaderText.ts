/** What a group header row says (plan 22 G4, G10): its status count and,
 *  per metric, the aggregate the board shows. */
import type { GroupAggregate, GroupCounts, MetricAggregate } from "../apiGroups";

export type CountTone = "total" | "running" | "waiting" | "stuck" | "failed";

/** The states a header names besides the total; done is the rest. */
const NAMED: readonly Exclude<CountTone, "total">[] = ["running", "waiting", "stuck", "failed"];

/** The total, then each state that is not done and has runs. */
export function countParts(c: GroupCounts): { text: string; tone: CountTone }[] {
  return [
    { text: String(c.total), tone: "total" },
    ...NAMED.filter((t) => c[t] > 0).map((t) => ({ text: `${c[t]} ${t}`, tone: t })),
  ];
}

/** `16 · 2 running · 1 failed`. */
export const countsText = (c: GroupCounts) => countParts(c).map((p) => p.text).join(" · ");

/** `16 runs, 2 running, 1 failed`, for a screen reader. */
export function spokenCounts(c: GroupCounts): string {
  const [, ...rest] = countParts(c);
  return [`${c.total} run${c.total === 1 ? "" : "s"}`, ...rest.map((p) => p.text)].join(", ");
}

/** A header's cell for one metric: *agg* of the group's values, the mean for
 *  `best` of a metric without a goal; its title names what it shows. */
export function aggregateCell(
  a: MetricAggregate | undefined, agg: GroupAggregate,
): { value: number | null; title: string | undefined } {
  if (!a || a.n === 0) return { value: null, title: undefined };
  const noGoal = agg === "best" && a.best === null;
  const used = noGoal ? "mean" : agg;
  return { value: a[used], title: `${used} of ${a.n}${noGoal ? " (no goal)" : ""}` };
}
