import { useMemo } from "react";
import { hashKey, useQuery } from "@tanstack/react-query";
import type { XMap } from "../util/xMetric";

/** Bumped whenever a caller's plain series (or fetcher) changes, so every
 *  refresh gets a key no other hook instance or earlier poll shares. */
let generation = 0;

export interface JoinedSeries<T> {
  data: T | null;
  error: Error | null;
}

/** What *fetchJoined* answers for *xMap*, re-fetched whenever the map or
 *  *token* (the plain series, so a poll refreshes the joins) changes; null
 *  until it arrives or when nothing needs a join. A poll keeps the previous
 *  join on screen; a new x map does not. On failure the charts stay on their
 *  plain axis and *error* says why. */
export function useJoinedSeries<T extends object>(
  xMap: XMap, fetchJoined: ((xMap: XMap) => Promise<T>) | undefined, token: unknown,
): JoinedSeries<T> {
  const refresh = useMemo(() => ++generation, [token, fetchJoined]);
  const mapHash = hashKey([xMap]);
  const query = useQuery({
    queryKey: ["joined-series", xMap, refresh],
    queryFn: () => fetchJoined!(xMap),
    enabled: Boolean(fetchJoined) && Object.keys(xMap).length > 0,
    placeholderData: (prev, prevQuery) =>
      prevQuery && hashKey([prevQuery.queryKey[1]]) === mapHash ? prev : undefined,
    staleTime: Infinity,
  });
  return { data: query.data ?? null, error: query.error };
}
