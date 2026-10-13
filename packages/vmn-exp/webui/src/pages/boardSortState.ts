/** The board's sort as the table and caption see it: the column, its order
 *  (the column's best-first one unless the URL flips it) and the click. */
import { metricGoal } from "../util";
import type { Order } from "../hooks/useLeaderboardView";
import { IDX_SORT, TIMESTAMP_SORT } from "./LeaderboardTable";
import { DATE_SORT_OF } from "./leaderboardColumns";

const NEWEST_FIRST = new Set([TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF)]);
type Schema = Parameters<typeof metricGoal>[0];

/** A column's best-first direction: newest first for time, else its goal's.
 *  When the goal is unknown (null), default to desc (high first). */
const bestOrder = (schema: Schema, col: string): Order =>
  !NEWEST_FIRST.has(col) && metricGoal(schema, col) === "min" ? "asc" : "desc";

export function boardSortState(
  sort: string | null, order: Order | null | undefined, schema: Schema,
  clickSort: (col: string, best: Order) => void,
) {
  return {
    sort,
    order: sort ? order ?? bestOrder(schema, sort) : null,
    reversed: Boolean(sort && order && order !== bestOrder(schema, sort)),
    onSort: (col: string) => clickSort(col, bestOrder(schema, col)),
  };
}
