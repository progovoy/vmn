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

/** A column whose best-first direction is not known yet (plan 32: no guess). */
export const UNKNOWN_BEST = "unknown";
type Best = Order | typeof UNKNOWN_BEST;

/** *bestOf* overrides a column's best-first direction where it knows one
 *  (the Jobs view's `job:value` follows its aggregate's goal), or names it
 *  {@link UNKNOWN_BEST}: that column then shows no direction unless the URL
 *  gives one, and a click on it only flips that one. */
export function boardSortState(
  sort: string | null, order: Order | null | undefined, schema: Schema,
  clickSort: (col: string, best: Order) => void,
  bestOf?: (col: string) => Best | null,
) {
  const best = (col: string) => {
    const b = bestOf?.(col) ?? bestOrder(schema, col);
    return b === UNKNOWN_BEST ? null : b;
  };
  const sortBest = sort ? best(sort) : null;
  return {
    sort,
    order: sort ? order ?? sortBest : null,
    reversed: Boolean(sort && order && sortBest && order !== sortBest),
    /** The sorted metric's goal (null without one); undefined for a non-metric sort. */
    goal: sort && isMetricSort(sort) ? metricGoal(schema, sort) : undefined,
    onSort: (col: string) => {
      const b = best(col) ?? (col === sort ? order : null);
      if (b) clickSort(col, b);
    },
  };
}
