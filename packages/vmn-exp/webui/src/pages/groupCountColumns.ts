/** The grouped board's count columns (plan 22 F10): which they are, when
 *  they show, the header group over them, what a group header's cell says,
 *  and the count sort the flat board has no use for. */
import type { GroupCounts } from "../apiGroups";
import { NO_GROUP } from "../util/groupBy";

/** The columns that count a group's runs, as the inner-run columns did. */
export const GROUP_COUNT_COLS = ["total", "waiting", "running", "done", "failed"] as const;
export type GroupCountCol = (typeof GROUP_COUNT_COLS)[number];

const COUNT_IDS = new Set<string>(GROUP_COUNT_COLS.map((c) => `c:${c}`));
export const isGroupCountId = (id: string | null | undefined) => Boolean(id && COUNT_IDS.has(id));

/** Whether count column *id* shows: on while grouped unless `hide=` names it. */
export const countColumnVisible = (id: string, hidden: ReadonlySet<string>, grouped: boolean) =>
  grouped && !hidden.has(id);

/** A group's count for column *col*; stuck runs count as failed. */
export const groupCount = (c: GroupCounts, col: GroupCountCol): number =>
  col === "failed" ? c.failed + c.stuck : c[col];

/** The class a count cell is coloured by: its state's tone, muted at zero. */
export const groupCountTone = (col: GroupCountCol, n: number) => (n === 0 ? "count-zero" : `tone-${col}`);

export const GROUP_COUNTS_LABEL = "Runs in group";
export const GROUP_COUNTS_HELP = "How many of each group's runs are in each state, on the group's header row";

/** One cell of the header group row: *span* columns from *start*. */
export interface HeadGroup {
  start: number;
  span: number;
  /** True for a block of adjacent count columns. */
  counts: boolean;
}

/** The group row over *ids*: one cell per contiguous block of count columns
 *  (a block dragged apart gets a label of its own), one per other column
 *  (a windowed table's gap columns too); null when no count column shows. */
export function headGroups(ids: readonly string[]): HeadGroup[] | null {
  const out: HeadGroup[] = [];
  ids.forEach((id, i) => {
    const counts = isGroupCountId(id);
    const last = out[out.length - 1];
    if (counts && last?.counts) last.span += 1;
    else out.push({ start: i, span: 1, counts });
  });
  return out.some((g) => g.counts) ? out : null;
}

/** The sort the board asks for: a count sort only orders groups, so the
 *  flat board drops one left in the URL (*group* null: not known yet). */
export const boardSort = (sort: string | null, group: string | null): string | null =>
  isGroupCountId(sort) && group === NO_GROUP ? null : sort;
