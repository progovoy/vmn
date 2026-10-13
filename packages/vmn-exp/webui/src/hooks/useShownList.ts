/** What a leaderboard list query shows: its data, else what it last showed
 *  (a refused query (400) and a pending one keep it); a 400 is the query's
 *  error, any other one fails the page only when nothing is shown. */
import { useRef } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { HttpError } from "../http";
import { isAbortError } from "../requestScope";

export function useShownList<T>(query: UseQueryResult<T, HttpError>, enabled: boolean) {
  const lastGood = useRef<T>();
  if (query.data) lastGood.current = query.data;
  const data = enabled ? query.data ?? lastGood.current : undefined;
  const err = query.error && !isAbortError(query.error) ? query.error : null;
  return {
    data,
    queryError: err?.status === 400 ? err.message : null,
    pageError: err && err.status !== 400 && !data ? String(err) : null,
  };
}
