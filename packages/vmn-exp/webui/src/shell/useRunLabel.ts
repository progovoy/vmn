/** A run's `@N name` for the crumb, read from what the pages already
 *  cached. It never fetches: the crumb waits for the Run page's request. */
import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { findCachedRow, runKey } from "../queries";
import type { ExperimentDetail } from "../types";
import type { RunLabel } from "./contracts";

/** A value derived from the query cache, re-read on every cache event.
 *  *read* returns a string so unchanged reads keep the snapshot stable. */
export function useCacheRead(read: (client: QueryClient) => string): string {
  const client = useQueryClient();
  const subscribe = useCallback(
    (onChange: () => void) => client.getQueryCache().subscribe(onChange), [client],
  );
  return useSyncExternalStore(subscribe, () => read(client));
}

function readLabel(client: QueryClient, ws: string, app: string, ref: string): RunLabel | undefined {
  const detail = client.getQueryData<ExperimentDetail>(runKey(ws, app, ref));
  const verstr = detail?.metadata.verstr ?? ref;
  // An older server's detail has no idx/name: the leaderboard row may.
  if (detail?.idx !== undefined) return { verstr, idx: detail.idx ?? null, name: detail.name ?? null };
  const row = findCachedRow(client, ws, app, verstr);
  if (row) return { verstr, idx: row.idx, name: row.name ?? null };
  return detail ? { verstr, idx: null, name: null } : undefined;
}

/** *app* is the URL tag form, *verstr* the URL's run ref. */
export function useRunLabel(ws?: string, app?: string, verstr?: string): RunLabel | undefined {
  const json = useCacheRead((client) => {
    if (!ws || !app || !verstr) return "";
    return JSON.stringify(readLabel(client, ws, app, verstr) ?? null);
  });
  return useMemo(() => (json ? JSON.parse(json) ?? undefined : undefined), [json]);
}
