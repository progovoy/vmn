import { useCallback, useRef, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { HttpError } from "../http";
import { PAGE_SIZE } from "../paging";
import { isAbortError, withSignal } from "../requestScope";
import { rowsKey, type RowsData, type RowsFilter } from "../queries";
import { refreshRows } from "../pages/leaderboardRefresh";
import { useShownList } from "./useShownList";
import { combineQueries } from "../util/searchQuery";

/** The first page for *f*. Unsorted-or-default-direction lists go through
 *  `api.experiments`; an explicit direction or archived rows need the paged call. */
function firstPage(ws: string, app: string, f: RowsFilter): Promise<RowsData> {
  if (f.order || f.archived) return api.experimentsPaged(ws, app, { ...f, offset: 0, limit: PAGE_SIZE });
  const req = f.query
    ? api.experiments(ws, app, f.sort, f.status, f.query)
    : api.experiments(ws, app, f.sort, f.status);
  return req.then((r) => ({ rows: [...r], total: r.total ?? r.length }));
}

/** Leaderboard rows for one filter, through the request cache: a revisited
 *  filter (Back) paints its cached rows at once and revalidates behind them.
 *  A refresh re-asks only the first page plus the running / on-screen rows
 *  past it (see refreshRows), and unchanged rows keep their identity. */
export function useLeaderboardRows(ws: string, app: string, filter: RowsFilter, enabled = true) {
  const client = useQueryClient();
  const key = rowsKey(ws, app, filter);
  /** Verstrs on screen right now — the table keeps it current. */
  const visibleRef = useRef<() => string[]>(() => []);

  const query = useQuery<RowsData, HttpError>({
    queryKey: key,
    enabled,
    // react-query aborts *signal* once this fetch is superseded or unwatched.
    queryFn: ({ signal }) => {
      const scoped = <T,>(fn: () => Promise<T>) => withSignal(signal, fn);
      return refreshRows({
        getRows: () => client.getQueryData<RowsData>(key)?.rows,
        fetchFirst: () => scoped(() => firstPage(ws, app, filter)),
        fetchWhere: (q, limit) =>
          scoped(() => api.experimentsPaged(ws, app, {
            ...filter, query: combineQueries(filter.query ?? "", q), offset: 0, limit,
          })),
        extraVerstrs: visibleRef.current(),
      });
    },
    // While a new filter loads, keep the previous rows on screen (a hook
    // instance only ever serves one app: the page is keyed by it).
    placeholderData: keepPreviousData,
    // refreshRows already keeps unchanged rows' identity, by verstr.
    structuralSharing: false,
  }, client);

  const { data, queryError, pageError } = useShownList(query, enabled);

  const [moreError, setMoreError] = useState<string | null>(null);
  const loadingMore = useRef(false);
  const keyHash = JSON.stringify(key);
  const loadMore = useCallback(async () => {
    const cur = client.getQueryData<RowsData>(key);
    if (!cur || loadingMore.current || cur.rows.length >= cur.total) return;
    loadingMore.current = true;
    try {
      const more = await api.experimentsPaged(ws, app, {
        ...filter, offset: cur.rows.length, limit: PAGE_SIZE,
      });
      const latest = client.getQueryData<RowsData>(key) ?? cur;
      const known = new Set(latest.rows.map((r) => r.verstr));
      client.setQueryData<RowsData>(key, {
        rows: [...latest.rows, ...more.rows.filter((r) => !known.has(r.verstr))],
        total: more.total,
      });
      setMoreError(null);
    } catch (e) {
      if (!isAbortError(e)) setMoreError(String(e));
    } finally {
      loadingMore.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, keyHash]);

  const refresh = useCallback(() => query.refetch().then((r) => r.data), [query.refetch]);

  return {
    rows: data?.rows,
    total: data ? Math.max(data.total, data.rows.length) : 0,
    queryError, pageError, moreError,
    loadMore, refresh, visibleRef,
    /** When the first page last arrived (ms since the epoch). */
    updatedAt: query.dataUpdatedAt,
  };
}
