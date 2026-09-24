/** Run-detail endpoints beyond the core `api` object: the paged run log. */
import { appTag, get } from "./http";
import type { LogEntry } from "./types";

export interface LogPage {
  entries: LogEntry[];
  total: number;
}

export function runLog(
  ws: string, app: string, verstr: string, offset: number, limit: number,
): Promise<LogPage> {
  const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return get<LogPage>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/` +
      `${encodeURIComponent(verstr)}/log?${qs}`,
  );
}
