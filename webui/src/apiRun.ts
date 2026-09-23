/** Run-detail endpoints beyond the core `api` object: the paged run log. */
import { appTag } from "./api";
import type { LogEntry } from "./types";

export interface LogPage {
  entries: LogEntry[];
  total: number;
}

export async function runLog(
  ws: string, app: string, verstr: string, offset: number, limit: number,
): Promise<LogPage> {
  const token = sessionStorage.getItem("vmn_token");
  const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  const res = await fetch(
    `/api/v1/workspaces/${ws}/apps/${appTag(app)}/experiments/` +
      `${encodeURIComponent(verstr)}/log?${qs}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
