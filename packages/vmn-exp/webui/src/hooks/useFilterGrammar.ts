import { useEffect, useMemo, useState } from "react";
import { useDebounce } from "./useDebounce";
import {
  EMPTY_FILTER, commitText, isPlainText, joinClauses, stateFromValues,
  type FilterState, type FilterValues,
} from "../util/filterTokens";

export interface FilterReports {
  onStatusChange?: (csv: string) => void;
  onQueryChange?: (query: string) => void;
  onSearchChange?: (text: string) => void;
  onBranchChange?: (branch: string) => void;
}

/** The filter bar's state: the committed filters plus the text being typed.
 *  The typed text already filters (debounced) as if committed, and each URL
 *  value is reported once per change. *paused* (the similar mode) holds the
 *  typed text back. */
export function useFilterGrammar(initial: FilterValues | undefined, paused: boolean, reports: FilterReports) {
  const [state, setState] = useState<FilterState>(() => stateFromValues(initial));
  const [draft, setDraft] = useState("");
  // Free text searches after a short pause; a query waits for a whole field name.
  const debounced = useDebounce(draft, isPlainText(draft) ? 200 : 300);
  const live = draft.trim() && !paused ? debounced : "";
  const effective = useMemo(() => commitText(state, live), [state, live]);

  const { onStatusChange, onQueryChange, onSearchChange, onBranchChange } = reports;
  const statusCsv = effective.statuses.join(",");
  const query = joinClauses(effective.clauses);
  useEffect(() => { onStatusChange?.(statusCsv); }, [statusCsv, onStatusChange]);
  useEffect(() => { onQueryChange?.(query); }, [query, onQueryChange]);
  useEffect(() => { onSearchChange?.(effective.search); }, [effective.search, onSearchChange]);
  useEffect(() => { onBranchChange?.(effective.branch); }, [effective.branch, onBranchChange]);

  return {
    state,
    setState,
    draft,
    setDraft,
    commit: () => { setState((s) => commitText(s, draft)); setDraft(""); },
    clear: () => { setState(EMPTY_FILTER); setDraft(""); },
  };
}
