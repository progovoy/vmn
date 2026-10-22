/** Query keys and cached reads shared across pages. */
import { useQuery, type QueryClient, useQueryClient } from "@tanstack/react-query";
import { api, type FacetOpts, type SubtreeMatches } from "./api";
import { withSignal } from "./requestScope";
import { fetchRunStatuses } from "./apiSeries";
import type { HeldChange } from "./pages/leaderboardRefresh";
import { SHARED_STALE_MS } from "./queryClient";
import type {
  AppRow, ExperimentDetail, ExperimentFacets, ExperimentRow, Meta, MetricsSchema, TopRuns, Workspace,
} from "./types";

/** Run detail served from cache for this long before a mount refetches it —
 *  long enough that a hover prefetch is what the Run page paints. */
export const RUN_STALE_MS = 5_000;

export interface RowsFilter {
  sort?: string;
  order?: "asc" | "desc";
  status?: string;
  query?: string;
  /** Include archived runs. */
  archived?: boolean;
  /** Top-level runs only (the Jobs view): all of them, or the jobs or single runs. */
  top?: TopRuns;
  /** A job's subtree only (its verstr). */
  scope?: string;
  /** With `top`: match `query` over each top-level run's subtree. */
  matchSubtree?: boolean;
}
export interface RowsData extends SubtreeMatches {
  rows: ExperimentRow[];
  total: number;
  /** The keyset cursor after the last row held (plan 23 S6); absent: page by offset. */
  next_cursor?: string | null;
  /** What a held refresh kept off screen (the `N new · show` bar, plan 23 W6). */
  held?: HeldChange;
}

/** Every cached leaderboard list of an app, whatever its filter. */
export const rowsPrefix = (ws: string, app: string) => ["experiments", ws, app] as const;
export const rowsKey = (ws: string, app: string, filter: RowsFilter) =>
  [...rowsPrefix(ws, app), filter] as const;
export const WORKSPACES_KEY = ["workspaces"] as const;
export const runKey = (ws: string, app: string, verstr: string) =>
  ["experiment", ws, app, verstr] as const;

const shared = { staleTime: SHARED_STALE_MS };

export function useWorkspaces() {
  const client = useQueryClient();
  return useQuery<Workspace[]>(
    { queryKey: WORKSPACES_KEY, queryFn: () => api.workspaces(), ...shared }, client,
  );
}

/** `/meta`, revalidated now and then: the role or auth may change. */
export function useMeta() {
  const client = useQueryClient();
  return useQuery<Meta>(
    { queryKey: ["meta"], queryFn: () => api.meta(), staleTime: 60_000, refetchOnWindowFocus: true },
    client,
  );
}

export function useApps(ws: string | undefined) {
  const client = useQueryClient();
  return useQuery<AppRow[]>(
    { queryKey: ["apps", ws], queryFn: () => api.apps(ws!), enabled: Boolean(ws), ...shared },
    client,
  );
}

/** The app's metric goals: null while loading, `{}` if it can't be read. */
export function useMetricsSchema(ws: string, app: string): MetricsSchema | null {
  const client = useQueryClient();
  const q = useQuery<MetricsSchema>(
    { queryKey: ["metrics-schema", ws, app], queryFn: () => api.metricsSchema(ws, app), ...shared },
    client,
  );
  return q.data ?? (q.isError ? {} : null);
}

/** The app's filter vocabulary, or null — loading, or a server without the
 *  facets endpoint; callers fall back to what the loaded rows show. */
export function useFacets(ws: string, app: string, opts?: FacetOpts): ExperimentFacets | null {
  const client = useQueryClient();
  return useQuery<ExperimentFacets>(facetsQuery(ws, app, opts), client).data ?? null;
}

/** The app's facets; with *opts*, over a job's subtree and filters (keyed
 *  under the app's, so refreshing the app's facets refreshes them too). */
export const facetsQuery = (ws: string, app: string, opts?: FacetOpts) => ({
  queryKey: opts ? ["facets", ws, app, opts] : ["facets", ws, app],
  queryFn: () => (opts ? api.facets(ws, app, opts) : api.facets(ws, app)),
  ...shared,
});

export const runQuery = (ws: string, app: string, verstr: string) => ({
  queryKey: runKey(ws, app, verstr),
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    withSignal(signal, () => api.experiment(ws, app, verstr)),
  staleTime: RUN_STALE_MS,
});

/** Warm the Run page's cache (on hover/focus of a row) — a no-op while fresh. */
export function prefetchRun(client: QueryClient, ws: string, app: string, verstr: string) {
  return client.prefetchQuery<ExperimentDetail>(runQuery(ws, app, verstr));
}

/** The longest list of the app's rows any leaderboard query has cached
 *  (empty when none has), e.g. to tell which params vary across its runs. */
export function cachedRows(client: QueryClient, ws: string, app: string): ExperimentRow[] {
  let best: ExperimentRow[] = [];
  for (const [, data] of client.getQueriesData<RowsData>({ queryKey: rowsPrefix(ws, app) })) {
    if (data && data.rows.length > best.length) best = data.rows;
  }
  return best;
}

/** A run's leaderboard row from any cached list, so the Run page can paint
 *  its header, status, metrics and params before the detail arrives. */
export function findCachedRow(
  client: QueryClient, ws: string, app: string, verstr: string,
): ExperimentRow | undefined {
  for (const [, data] of client.getQueriesData<RowsData>({ queryKey: rowsPrefix(ws, app) })) {
    const row = data?.rows.find((r) => r.verstr === verstr);
    if (row) return row;
  }
  return undefined;
}

/** A run's row from the index (an index read, milliseconds: what a page
 *  paints before the run detail's per-run store reads), null when none. */
export const runRowQuery = (ws: string, app: string, verstr: string) => ({
  queryKey: ["run-row", ws, app, verstr] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => withSignal(signal, () => fetchRunStatuses(ws, app, [verstr]))
    .then((rows) => (rows[verstr] as ExperimentRow | undefined) ?? null),
  staleTime: RUN_STALE_MS,
});

/** *verstr*'s row: a board's cached one (read once, when the query starts),
 *  else looked up in the index; *settled* once either is known (or failed). */
export function useRunRow(ws: string, app: string, verstr: string) {
  const client = useQueryClient();
  const looked = useQuery({
    ...runRowQuery(ws, app, verstr), initialData: () => findCachedRow(client, ws, app, verstr),
  }, client);
  return { row: looked.data ?? undefined, settled: !looked.isPending };
}
