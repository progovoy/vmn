/** A board's URL filters as the one server filter its rows are asked with
 *  (the All runs board, a job's Runs tab, the Jobs view): search, branch and
 *  the typed query travel as one query; a count sort orders groups only
 *  (plan 22 F10), so the flat board drops it. */
import { useMemo } from "react";
import { boardSort } from "../util/groupCountSort";
import { branchClause, combineQueries, searchClause } from "../util/searchQuery";
import { IDX_SORT } from "../pages/LeaderboardHead";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>,
  "query" | "search" | "branch" | "status" | "archived" | "sort" | "order">;

/** The server query of *view*'s query, search and branch. */
export const boardQuery = (view: View) =>
  combineQueries(combineQueries(view.query, searchClause(view.search)), branchClause(view.branch));

/** Whether any of *view*'s filters is set (a search the server can't carry too). */
export const boardFiltered = (view: View) =>
  Boolean(view.query || view.status || view.search || view.branch || view.archived);

/** *extra* (a scope, `top`, ...) joins the filter; its keys never change. */
export function useBoardFilter<E extends Record<string, unknown>>(view: View, group: string | null, extra: E) {
  const serverQuery = boardQuery(view);
  const sort = boardSort(view.sort, group);
  const extraDeps = Object.values(extra);
  const filter = useMemo(() => ({
    sort: sort ?? IDX_SORT,
    order: sort ? view.order : undefined,
    status: view.status || undefined,
    query: serverQuery || undefined,
    archived: view.archived || undefined,
    ...extra,
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [sort, view.order, view.status, serverQuery, view.archived, ...extraDeps]);
  return { sort, serverQuery, filter, filtered: boardFiltered(view) };
}
