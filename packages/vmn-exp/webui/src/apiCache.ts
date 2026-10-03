/** Workspace cache maintenance (admin): GET .../cache/status, POST .../cache/resync[?full=1]. */
import { get, post } from "./http";

export interface CacheStatus {
  workspace: string;
  state: "idle" | "rebuilding";
  progress: { done: number; total: number };
  drift: number;
  rebuilds: number;
  last_rebuild_reason: string | null;
  journal_lag_sec: number | null;
  apps: Record<string, { generation: number; records: number; drift: number; last_reconcile_at: number | null }>;
}

const base = (ws: string) => `/workspaces/${encodeURIComponent(ws)}/cache`;

export const apiCache = {
  status: (ws: string) => get<CacheStatus>(`${base(ws)}/status`),
  resync: (ws: string, full: boolean) =>
    post<CacheStatus>(`${base(ws)}/resync${full ? "?full=1" : ""}`, {}),
};
