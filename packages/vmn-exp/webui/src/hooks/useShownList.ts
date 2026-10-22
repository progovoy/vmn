/** What a leaderboard list query shows: its data, else what it last showed
 *  for the same *view* (a refused query (400) and a pending one keep it,
 *  marked `stale`); another view's rows are never shown. A 400 is the
 *  query's error; any other one fails the page when nothing is shown, else
 *  is `staleError`, said over the rows kept. */
import { useRef } from "react";
import type { QueryClient, QueryKey, UseQueryResult } from "@tanstack/react-query";
import type { HttpError } from "../http";
import type { RowsFilter } from "../queries";
import { isAbortError } from "../requestScope";
import { newestOfView } from "../util/newestCached";

/** Which list a filter asks for: the top-level side and the scope; the rest
 *  only narrows or orders it. */
export const listViewOf = (f: RowsFilter) => JSON.stringify([f.top ?? null, f.scope ?? null]);

/** *key* is the list query's, its filter last: a mount on a filter never
 *  answered (Back) shows the view's newest cached rows of another filter. */
export function useShownList<T>(
  query: UseQueryResult<T, HttpError>, enabled: boolean, client: QueryClient, key: QueryKey,
) {
  const view = listViewOf(key[key.length - 1] as RowsFilter);
  const lastGood = useRef<{ view: string; data: T }>();
  const looked = useRef<string>();
  if (query.data) lastGood.current = { view, data: query.data };
  else if (lastGood.current?.view !== view && looked.current !== view) {
    // Looked up once per view: the cache is scanned on the mount or switch only.
    looked.current = view;
    const cached = newestOfView<T>(client, key, (f) => listViewOf(f as RowsFilter) === view);
    if (cached !== undefined) lastGood.current = { view, data: cached };
  }
  const kept = lastGood.current?.view === view ? lastGood.current.data : undefined;
  const data = enabled ? query.data ?? kept : undefined;
  const err = query.error && !isAbortError(query.error) ? query.error : null;
  const failed = err && err.status !== 400 ? String(err) : null;
  // Cached before this mount (Back) and being revalidated: shown at once, as updating.
  const revalidating = query.isFetching && !query.isFetchedAfterMount;
  return {
    data,
    stale: data !== undefined && (query.data === undefined || revalidating),
    queryError: err?.status === 400 ? err.message : null,
    pageError: data ? null : failed,
    /** The page failed as not found (404): e.g. a scope a loading index does not hold yet. */
    missing: !data && err?.status === 404,
    staleError: data ? failed : null,
  };
}
