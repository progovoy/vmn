/** The board's sort as the table and caption see it: the column, its order
 *  (the column's best-first one unless the URL flips it) and the click. */
import { goalOrder, metricGoal } from "../util";
import type { Order } from "../hooks/useLeaderboardView";
import { IDX_SORT, TIMESTAMP_SORT } from "./LeaderboardTable";
import { DATE_SORT_OF, DURATION_SORT_OF } from "./leaderboardColumns";

const HIGH_FIRST = new Set([
  TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF), ...Object.values(DURATION_SORT_OF),
]);
/** The Jobs view's and the group counts' sorts, all most first. */
const COUNT_PREFIXES = ["job:", "c:"];
type Schema = Parameters<typeof metricGoal>[0];

/** A column's best-first direction: newest (or highest) first for time,
 *  durations and counts, a to z for a tag (plan 28 P4), else its metric's
 *  goal: a metric without one sorts ascending (plan 32 F4). */
const bestOrder = (schema: Schema, col: string): Order => {
  if (col.startsWith("tags.")) return "asc";
  if (!isMetricSort(col)) return "desc";
  return goalOrder(metricGoal(schema, col));
};

const isMetricSort = (col: string) =>
  !col.startsWith("tags.") && !HIGH_FIRST.has(col) && !COUNT_PREFIXES.some((p) => col.startsWith(p));

/** *bestOf* overrides a column's best-first direction where it knows one
 *  (the Jobs view's `job:value` follows its aggregate's goal). */
export function boardSortState(
  sort: string | null, order: Order | null | undefined, schema: Schema,
  clickSort: (col: string, best: Order) => void,
  bestOf?: (col: string) => Order | null,
) {
  const best = (col: string) => bestOf?.(col) ?? bestOrder(schema, col);
  return {
    sort,
    order: sort ? order ?? best(sort) : null,
    reversed: Boolean(sort && order && order !== best(sort)),
    /** The sorted metric's goal (null without one); undefined for a non-metric sort. */
    goal: sort && isMetricSort(sort) ? metricGoal(schema, sort) : undefined,
    onSort: (col: string) => clickSort(col, best(col)),
  };
}
