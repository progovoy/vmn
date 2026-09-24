/** Query keys and cached reads shared across pages. */
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { withSignal } from "./requestScope";
import { SHARED_STALE_MS, useAppQueryClient } from "./queryClient";
import type {
  AppRow, ExperimentDetail, ExperimentFacets, ExperimentRow, Meta, MetricsSchema, Workspace,
} from "./types";

/** Run detail served from cache for this long before a mount refetches it —
 *  long enough that a hover prefetch is what the Run page paints. */
export const RUN_STALE_MS = 5_000;

export interface RowsFilter {
  sort?: string;
  order?: "asc" | "desc";
  status?: string;
  query?: string;
}
export interface RowsData {
  rows: ExperimentRow[];
  total: number;
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
  const client = useAppQueryClient();
  return useQuery<Workspace[]>(
    { queryKey: WORKSPACES_KEY, queryFn: () => api.workspaces(), ...shared }, client,
  );
}

export function useMeta() {
  const client = useAppQueryClient();
  return useQuery<Meta>(
    { queryKey: ["meta"], queryFn: () => api.meta(), staleTime: Infinity }, client,
  );
}

export function useApps(ws: string | undefined) {
  const client = useAppQueryClient();
  return useQuery<AppRow[]>(
    { queryKey: ["apps", ws], queryFn: () => api.apps(ws!), enabled: Boolean(ws), ...shared },
    client,
  );
}

/** The app's metric goals: null while loading, `{}` if it can't be read. */
export function useMetricsSchema(ws: string, app: string): MetricsSchema | null {
  const client = useAppQueryClient();
  const q = useQuery<MetricsSchema>(
    { queryKey: ["metrics-schema", ws, app], queryFn: () => api.metricsSchema(ws, app), ...shared },
    client,
  );
  return q.data ?? (q.isError ? {} : null);
}

/** The app's filter vocabulary, or null — loading, or a server without the
 *  facets endpoint; callers fall back to what the loaded rows show. */
export function useFacets(ws: string, app: string): ExperimentFacets | null {
  const client = useAppQueryClient();
  const q = useQuery<ExperimentFacets>(
    { queryKey: ["facets", ws, app], queryFn: () => api.facets(ws, app), ...shared },
    client,
  );
  return q.data ?? null;
}

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
