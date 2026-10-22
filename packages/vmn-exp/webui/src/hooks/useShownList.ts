/** What a leaderboard list query shows: its data, else what it last showed
 *  for the same *view* (a refused query (400) and a pending one keep it,
 *  marked `stale`); another view's rows are never shown. A 400 is the
 *  query's error; any other one fails the page when nothing is shown, else
 *  is `staleError`, said over the rows kept. */
import { useRef } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { HttpError } from "../http";
import type { RowsFilter } from "../queries";
import { isAbortError } from "../requestScope";

/** Which list a filter asks for: the top-level side and the scope; the rest
 *  only narrows or orders it. */
export const listViewOf = (f: RowsFilter) => JSON.stringify([f.top ?? null, f.scope ?? null]);

export function useShownList<T>(query: UseQueryResult<T, HttpError>, enabled: boolean, view: string) {
  const lastGood = useRef<{ view: string; data: T }>();
  if (query.data) lastGood.current = { view, data: query.data };
  const kept = lastGood.current?.view === view ? lastGood.current.data : undefined;
  const data = enabled ? query.data ?? kept : undefined;
  const err = query.error && !isAbortError(query.error) ? query.error : null;
  const failed = err && err.status !== 400 ? String(err) : null;
  return {
    data,
    stale: data !== undefined && query.data === undefined,
    queryError: err?.status === 400 ? err.message : null,
    pageError: data ? null : failed,
    /** The page failed as not found (404): e.g. a scope a loading index does not hold yet. */
    missing: !data && err?.status === 404,
    staleError: data ? failed : null,
  };
}
