/** The shell's live reads. Failures stay in the query result (react-query
 *  never throws them to an error boundary by default). */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { apiShell } from "../apiShell";
import type { AppStatus, GitContext } from "./contracts";
import type { Meta } from "../types";

const GIT_POLL_MS = 30_000;

/** Status polls fast while something runs (or is stuck), slowly otherwise. */
export const statusPollMs = (status?: AppStatus) =>
  status && status.counts.running + status.counts.stuck > 0 ? 15_000 : 60_000;

/** `/meta` under useMeta's key, but revalidated: the role or auth may change. */
export function useMetaLive() {
  return useQuery<Meta>({
    queryKey: ["meta"], queryFn: () => api.meta(), staleTime: 60_000, refetchOnWindowFocus: true,
  });
}

/** Pass `enabled = isGit`: a store workspace has no checkout to ask about.
 *  Interval refetches pause while the tab is hidden (react-query's default). */
export function useGitContext(ws: string | undefined, enabled: boolean) {
  return useQuery<GitContext>({
    queryKey: ["git", ws],
    queryFn: () => apiShell.gitContext(ws!),
    enabled: Boolean(ws) && enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
    refetchInterval: GIT_POLL_MS,
  });
}

/** *tag* is the app in URL tag form. */
export function useAppStatus(ws: string | undefined, tag: string | undefined) {
  return useQuery<AppStatus>({
    queryKey: ["app-status", ws, tag],
    queryFn: () => apiShell.appStatus(ws!, tag!),
    enabled: Boolean(ws && tag),
    refetchInterval: (query) => statusPollMs(query.state.data),
  });
}
