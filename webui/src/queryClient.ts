/** The request cache: stale-while-revalidate + dedupe via react-query.
 *
 *  Pages paint whatever the cache holds for their key at once and revalidate
 *  in the background; identical requests in flight share one fetch. */
import { useContext, useState } from "react";
import { notifyManager, QueryClient, QueryClientContext } from "@tanstack/react-query";

// Deliver cache notifications on a microtask rather than a macrotask: a
// response lands in the same turn it resolved in, so a page reacts to it (a
// poll stopping once nothing runs) before any other timer fires.
notifyManager.setScheduler(queueMicrotask);

/** Freshness of app-wide resources (workspaces, apps, metrics schema,
 *  facets): they change rarely, so they are not refetched on every mount. */
export const SHARED_STALE_MS = 60_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Pages poll on their own cadence; a retry or a focus refetch would
        // only repeat a request that is about to be repeated anyway.
        retry: false,
        refetchOnWindowFocus: false,
        gcTime: 10 * 60_000,
      },
    },
  });
}

/** The app's client, or — rendered outside a provider (a page under test) —
 *  one private to this component, so a page never needs the provider to work. */
export function useAppQueryClient(): QueryClient {
  const provided = useContext(QueryClientContext);
  const [own] = useState(() => (provided ? null : createQueryClient()));
  return provided ?? own!;
}
