/** The grouped list payload (plan 22 K1) as the board caches it, and the
 *  pages added to it: more groups, or more rows of one group. */
import type { GroupedPage, RunGroup } from "../apiGroups";
import type { BoardGroup, GroupedRows } from "./groupItems";

const boardGroup = ({ rows, ...g }: RunGroup): BoardGroup => ({ ...g, verstrs: rows.map((r) => r.verstr) });

export function cacheOf(page: GroupedPage): GroupedRows {
  return {
    rows: page.groups.flatMap((g) => g.rows),
    total: page.total_rows,
    groups: page.groups.map(boardGroup),
    total_groups: page.total_groups,
  };
}

/** *cur* with the groups of *next* it lacks appended. */
export function withGroups(cur: GroupedRows, next: GroupedPage): GroupedRows {
  const known = new Set(cur.groups.map((g) => g.key));
  const fresh = next.groups.filter((g) => !known.has(g.key));
  return {
    rows: [...cur.rows, ...fresh.flatMap((g) => g.rows)],
    total: next.total_rows,
    groups: [...cur.groups, ...fresh.map(boardGroup)],
    total_groups: next.total_groups,
  };
}

/** *cur* with *page*'s rows appended to its group (whose counts it takes). */
export function withGroupRows(cur: GroupedRows, page: RunGroup): GroupedRows {
  const known = new Set(cur.rows.map((r) => r.verstr));
  const fresh = page.rows.filter((r) => !known.has(r.verstr));
  return {
    ...cur,
    rows: [...cur.rows, ...fresh],
    groups: cur.groups.map((g) => g.key !== page.key ? g : {
      ...boardGroup({ ...page, rows: [] }), verstrs: [...g.verstrs, ...fresh.map((r) => r.verstr)],
    }),
  };
}

/** The most rows any loaded group holds. */
export const deepestGroup = (data: GroupedRows | undefined) =>
  Math.max(0, ...(data?.groups ?? []).map((g) => g.verstrs.length));
