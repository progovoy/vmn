/** The board's sort as the table and caption see it: the column, its order
 *  (the column's best-first one unless the URL flips it) and the click. */
import { metricGoal } from "../util";
import type { Order } from "../hooks/useLeaderboardView";
import { IDX_SORT, TIMESTAMP_SORT } from "./LeaderboardTable";
import { DATE_SORT_OF } from "./leaderboardColumns";

const NEWEST_FIRST = new Set([TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF)]);
type Schema = Parameters<typeof metricGoal>[0];

/** A column's best-first direction: newest first for time, a to z for a
 *  tag (plan 28 P4), else its goal's. When the goal is unknown (null),
 *  default to desc (high first). */
const bestOrder = (schema: Schema, col: string): Order =>
  col.startsWith("tags.") || (!NEWEST_FIRST.has(col) && metricGoal(schema, col) === "min") ? "asc" : "desc";

/** *bestOf* overrides a column's best-first direction where it knows one
 *  (the Jobs view's `job:best` follows its metric's goal). */
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
    onSort: (col: string) => clickSort(col, best(col)),
  };
}
