/** The shell's live reads. Failures stay in the query result (react-query
 *  never throws them to an error boundary by default). */
import { useQuery } from "@tanstack/react-query";
import { apiShell } from "../apiShell";
import { get } from "../http";
import { refreshingOnOldData } from "../util/freshness";
import type { AppStatus, GitContext } from "./contracts";

const GIT_POLL_MS = 30_000;

/** Status polls fastest while an index loads or a refresh runs on old data,
 *  fast while something runs (or is stuck), slowly otherwise. */
const pollMs = (statuses: AppStatus[]) =>
  statuses.some((s) => s.indexing || refreshingOnOldData(s.freshness)) ? 2_000
    : statuses.some((s) => s.counts.running + s.counts.stuck > 0) ? 15_000 : 60_000;
export const statusPollMs = (status?: AppStatus) => pollMs(status ? [status] : []);

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

/** A status this fresh is served from cache to a newly mounted reader. */
const STATUS_STALE_MS = 10_000;

const appStatusQuery = (ws: string | undefined, tag: string | undefined) => ({
  queryKey: ["app-status", ws, tag],
  queryFn: () => apiShell.appStatus(ws!, tag!),
  enabled: Boolean(ws && tag),
  staleTime: STATUS_STALE_MS,
});

/** The app's status, read from the cache the shell's poller keeps fresh.
 *  *tag* is the app in URL tag form. */
export function useAppStatus(ws: string | undefined, tag: string | undefined) {
  return useQuery<AppStatus>(appStatusQuery(ws, tag));
}

/** The one observer that polls the status (the shell mounts it): every
 *  useAppStatus reader of the same app sees each answer. Returns it. */
export function useAppStatusPoll(ws: string | undefined, tag: string | undefined) {
  return useQuery<AppStatus>({
    ...appStatusQuery(ws, tag),
    refetchInterval: (query) => statusPollMs(query.state.data),
  }).data;
}

/** Every app's status in a workspace, keyed by tag: one request for the
 *  apps page, polled fast while any app has something running or stuck. */
export function useAppsStatus(ws: string) {
  return useQuery<Record<string, AppStatus>>({
    queryKey: ["apps-status", ws],
    queryFn: () => get<Record<string, AppStatus>>(`/workspaces/${ws}/apps-status`),
    staleTime: STATUS_STALE_MS,
    refetchInterval: (query) => pollMs(Object.values(query.state.data ?? {})),
  });
}
