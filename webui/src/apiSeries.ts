/** Batched reads for the overlay: every run's series in one request, and the
 *  runs' status rows in another. Kept apart from api.ts so the pages whose
 *  tests mock `./api` still reach these through their own module. */
import type { ExperimentRow, RunStatus, SeriesPoint } from "./types";
import { authHeaders, BASE, get } from "./http";
import { currentSignal } from "./requestScope";

export interface SeriesBatch {
  series: Record<string, Record<string, SeriesPoint[]>>;
  series_total?: Record<string, Record<string, number>>;
  /** Requested runs the server does not know. */
  missing?: string[];
}

/** The URL form of an app name (as `appTag` in api.ts). */
const tag = (app: string) => app.replaceAll("/", "-");

async function postJson<T>(path: string, body: unknown, signal = currentSignal()): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw Object.assign(new Error(b.detail || `HTTP ${res.status}`), { status: res.status });
  }
  return res.json();
}

/** *keys* null means every metric; *maxPoints* thins each series server-side. */
export function fetchSeriesBatch(
  ws: string, app: string, verstrs: string[], keys: string[] | null, maxPoints: number,
): Promise<SeriesBatch> {
  return postJson<SeriesBatch>(`/workspaces/${ws}/apps/${tag(app)}/series`, {
    verstrs, keys, max_points: maxPoints,
  });
}

/** Status fields (running? started when?) of just *verstrs*, by verstr. */
export async function fetchRunStatuses(
  ws: string, app: string, verstrs: string[],
): Promise<Record<string, Partial<RunStatus>>> {
  const q = `verstr in (${verstrs.map((v) => JSON.stringify(v)).join(", ")})`;
  const p = new URLSearchParams({ offset: "0", limit: String(verstrs.length), q });
  const body = await get<ExperimentRow[] | { rows: ExperimentRow[] }>(
    `/workspaces/${ws}/apps/${tag(app)}/experiments?${p}`,
  );
  const rows = Array.isArray(body) ? body : body.rows;
  return Object.fromEntries(rows.map((r) => [r.verstr, r]));
}
