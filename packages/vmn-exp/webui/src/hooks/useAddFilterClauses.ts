/** Adding clauses to a board's filters from outside its filter bar (a
 *  facet value, a group opened as a filter, plan 23 §3.4): *gen* is bumped
 *  each time, the filter bar's key, so it re-reads the URL. */
import { useCallback, useState } from "react";
import { addFilterClause } from "../util/groupClause";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>, "setFilters" | "status" | "query" | "search" | "branch">;

export function useAddFilterClauses(view: View) {
  const [gen, setGen] = useState(0);
  const resetFilter = useCallback(() => setGen((g) => g + 1), []);
  const { setFilters, status, query, search, branch } = view;
  /** With *ungroup*, the grouping goes too (a group's own clause). */
  const addClauses = useCallback((clauses: string[], ungroup = false) => {
    setFilters(clauses.reduce(addFilterClause, { status, query, search, branch }), ungroup);
    resetFilter();
  }, [setFilters, status, query, search, branch, resetFilter]);
  const openGroup = useCallback((clause: string) => addClauses([clause], true), [addClauses]);
  return { gen, resetFilter, addClauses, openGroup };
}
