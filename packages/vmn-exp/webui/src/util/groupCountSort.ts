/** A grouped board's sort of groups by a count (plan 22 F10, F13): the
 *  choices the Group by menu offers, and the count sort the flat board has
 *  no use for. */
import { NO_GROUP } from "./groupBy";

/** The Group by menu's "Sort groups" choices: null orders by the aggregate. */
export const GROUP_SORTS: readonly { value: string | null; label: string }[] = [
  { value: null, label: "aggregate" },
  { value: "c:total", label: "runs" },
  { value: "c:running", label: "running" },
  { value: "c:failed", label: "failed" },
  { value: "c:waiting", label: "waiting" },
  { value: "c:done", label: "succeeded" },
];

const COUNT_IDS = new Set(GROUP_SORTS.flatMap((o) => (o.value ? [o.value] : [])));
export const isGroupCountId = (id: string | null | undefined) => Boolean(id && COUNT_IDS.has(id));

/** The group sort *sort* is: its count, else null (the aggregate). */
export const groupSortOf = (sort: string | null): string | null => (isGroupCountId(sort) ? sort : null);

/** The sort the board asks for: a count sort only orders groups, so the
 *  flat board drops one left in the URL (*group* null: not known yet). */
export const boardSort = (sort: string | null, group: string | null): string | null =>
  isGroupCountId(sort) && group === NO_GROUP ? null : sort;
