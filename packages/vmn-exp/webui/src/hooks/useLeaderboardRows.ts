import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { HttpError } from "../http";
import { PAGE_SIZE } from "../paging";
import { isAbortError, withSignal } from "../requestScope";
import { rowsKey, type RowsData, type RowsFilter } from "../queries";
import { refreshRows } from "../pages/leaderboardRefresh";
import { stabilizeRows } from "../util/stableRows";
import { useShownList } from "./useShownList";
import { combineQueries } from "../util/searchQuery";
import type { ExperimentRow } from "../types";

/** The first page for *f*. Unsorted-or-default-direction lists go through
 *  `api.experiments`; an explicit direction, archived, top-level or scoped rows need the paged call. */
function firstPage(ws: string, app: string, f: RowsFilter): Promise<RowsData> {
  if (f.order || f.archived || f.top || f.scope) return api.experimentsPaged(ws, app, { ...f, offset: 0, limit: PAGE_SIZE });
  const req = f.query
    ? api.experiments(ws, app, f.sort, f.status, f.query)
    : api.experiments(ws, app, f.sort, f.status);
  return req.then((r) => ({
    rows: [...r], total: r.total ?? r.length, next_cursor: r.next_cursor,
  }));
}

/** A prefetched first page counts as fresh this long: a view switched to
 *  paints it with no request of its own. Any other answer is stale at once. */
export const PREFETCH_FRESH_MS = 30_000;
const prefetched = new WeakSet<object>();

const rowsStaleTime = (q: Query<RowsData, HttpError>) =>
  (q.state.data && prefetched.has(q.state.data) ? PREFETCH_FRESH_MS : 0);

/** Fetch the first page of the board *filter* asks for into the cache (a
 *  no-op while a fresh one is there), as its board would. */
export function prefetchRows(client: QueryClient, ws: string, app: string, filter: RowsFilter) {
  return client.prefetchQuery<RowsData, HttpError>({
    queryKey: rowsKey(ws, app, filter),
    queryFn: ({ signal }) => withSignal(signal, () => firstPage(ws, app, filter)).then((page) => {
      prefetched.add(page);
      return page;
    }),
    staleTime: PREFETCH_FRESH_MS,
  });
}

/** What the table tells the rows (plan 23 W6): whether a refresh must hold
 *  the rows in place (scrolled down, rows selected), and how to get back to
 *  the top of the list. */
export type BoardViewport = { held: () => boolean; toTop: () => void };

/** Whether rows past *data*'s are left: by its keyset cursor, else its total. */
const hasMoreOf = (data: RowsData) =>
  (data.next_cursor !== undefined ? data.next_cursor !== null : data.rows.length < data.total);

/** Re-asked top-level rows of a subtree search, by verstr: a subtree query
 *  `and verstr in (...)` would ask for runs that are both, so they are
 *  re-read by their own fields and keep the `matched` count they had. */
async function byVerstrKeepingMatched(
  ws: string, app: string, f: RowsFilter, q: string, limit: number, held: readonly ExperimentRow[] = [],
) {
  const page = await api.experimentsPaged(ws, app, { ...f, query: q, matchSubtree: false, offset: 0, limit });
  const matched = new Map(held.map((r) => [r.verstr, r.matched] as const));
  return { ...page, rows: page.rows.map((r) => ({ ...r, matched: matched.get(r.verstr) })) };
}

/** Leaderboard rows for one filter, through the request cache: a revisited
 *  filter (Back) paints its cached rows at once and revalidates behind them.
 *  A refresh re-asks only the first page plus the running / on-screen rows
 *  past it (see refreshRows), and unchanged rows keep their identity.
 *  Pages after the first follow the server's keyset cursor (plan 23 S6).
 *  While the table holds its rows (*viewportRef*) a refresh reshuffles
 *  nothing: `pending` says what is new until `showNew` reloads page 1. */
export function useLeaderboardRows(ws: string, app: string, filter: RowsFilter, enabled = true) {
  const client = useQueryClient();
  const key = rowsKey(ws, app, filter);
  /** Verstrs on screen right now — the table keeps it current. */
  const visibleRef = useRef<() => string[]>(() => []);
  const viewportRef = useRef<BoardViewport>({ held: () => false, toTop: () => {} });

  const query = useQuery<RowsData, HttpError>({
    queryKey: key,
    enabled,
    staleTime: rowsStaleTime,
    // react-query aborts *signal* once this fetch is superseded or unwatched.
    queryFn: ({ signal }) => {
      const scoped = <T,>(fn: () => Promise<T>) => withSignal(signal, fn);
      return refreshRows({
        getRows: () => client.getQueryData<RowsData>(key)?.rows,
        fetchFirst: () => scoped(() => firstPage(ws, app, filter)),
        fetchWhere: (q, limit) => scoped(() => filter.matchSubtree
          ? byVerstrKeepingMatched(ws, app, filter, q, limit, client.getQueryData<RowsData>(key)?.rows)
          : api.experimentsPaged(ws, app, {
            ...filter, query: combineQueries(filter.query ?? "", q), offset: 0, limit,
          })),
        extraVerstrs: visibleRef.current(),
        hold: viewportRef.current.held(),
        getCursor: () => client.getQueryData<RowsData>(key)?.next_cursor,
      });
    },
    // refreshRows already keeps unchanged rows' identity, by verstr.
    structuralSharing: false,
  }, client);

  // While a new filter loads, the view's previous rows stay on screen,
  // marked stale (a hook instance only ever serves one app: the page is keyed by it).
  const { data, stale, queryError, pageError, staleError, missing } = useShownList(query, enabled, client, key);

  const [moreError, setMoreError] = useState<string | null>(null);
  const loadingMore = useRef(false);
  const keyHash = JSON.stringify(key);
  const loadMore = useCallback(async () => {
    const cur = client.getQueryData<RowsData>(key);
    if (!cur || loadingMore.current || !hasMoreOf(cur)) return;
    loadingMore.current = true;
    try {
      const from = cur.next_cursor ? { cursor: cur.next_cursor } : { offset: cur.rows.length };
      const more = await api.experimentsPaged(ws, app, { ...filter, ...from, limit: PAGE_SIZE });
      const latest = client.getQueryData<RowsData>(key) ?? cur;
      const known = new Set(latest.rows.map((r) => r.verstr));
      client.setQueryData<RowsData>(key, {
        ...latest,
        rows: [...latest.rows, ...more.rows.filter((r) => !known.has(r.verstr))],
        total: more.total,
        next_cursor: more.next_cursor,
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

  const showNew = useCallback(async () => {
    try {
      const first = await firstPage(ws, app, filter);
      const cur = client.getQueryData<RowsData>(key);
      client.setQueryData<RowsData>(key, { ...first, rows: stabilizeRows(cur?.rows, first.rows) });
      viewportRef.current.toTop();
    } catch (e) {
      if (!isAbortError(e)) setMoreError(String(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, keyHash]);

  return {
    rows: data?.rows,
    total: data ? Math.max(data.total, data.rows.length) : 0,
    /** A Jobs view search's counts (plan 23 W11), when the server sent them. */
    matches: data?.runs_matched === undefined ? undefined
      : { jobs: data.jobs_matched ?? 0, runs: data.runs_matched },
    stale, queryError, pageError, staleError, missing, moreError,
    loadMore, refresh, visibleRef, viewportRef, showNew,
    hasMore: data ? hasMoreOf(data) : false,
    /** What a held refresh kept off screen, null when nothing is waiting. */
    pending: data?.held ?? null,
    /** When the first page last arrived (ms since the epoch). */
    updatedAt: query.dataUpdatedAt,
  };
}
