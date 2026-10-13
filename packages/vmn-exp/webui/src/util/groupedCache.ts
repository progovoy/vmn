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
    aggregate: page.aggregate,
    running: page.running,
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
    aggregate: next.aggregate,
    running: next.running,
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

/** `[key, offset, limit]` of each group of *next* that *prev* held more
 *  rows of: the rows a refresh re-asks so a group keeps its depth. */
export function deeperGroups(prev: GroupedRows | undefined, next: GroupedRows): [string, number, number][] {
  const held = new Map((prev?.groups ?? []).map((g) => [g.key, g.verstrs.length]));
  return next.groups.flatMap((g): [string, number, number][] => {
    const offset = g.verstrs.length;
    const limit = Math.min(held.get(g.key) ?? 0, g.rows_total) - offset;
    return limit > 0 ? [[g.key, offset, limit]] : [];
  });
}
