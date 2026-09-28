/** Batched reads for the overlay: every run's series in one request, and the
 *  runs' status rows in another. Kept apart from api.ts so the pages whose
 *  tests mock `./api` still reach these through their own module. */
import type { ExperimentRow, RunStatus, SeriesPoint } from "./types";
import { appTag, get, post } from "./http";
import { verstrInQuery } from "./util/searchQuery";

export interface SeriesBatch {
  series: Record<string, Record<string, SeriesPoint[]>>;
  series_total?: Record<string, Record<string, number>>;
  /** Per run: the metrics that declare an x-axis metric. */
  step_metrics?: Record<string, Record<string, string>>;
  /** Requested runs the server does not know. */
  missing?: string[];
}

/** *keys* null means every metric; *maxPoints* thins each series server-side.
 *  *x* (`{metric: x metric}`) joins those metrics on their x metric: their
 *  points carry `x`, and points without one are left out. */
export function fetchSeriesBatch(
  ws: string, app: string, verstrs: string[], keys: string[] | null, maxPoints: number,
  x?: Record<string, string>,
): Promise<SeriesBatch> {
  return post<SeriesBatch>(`/workspaces/${ws}/apps/${appTag(app)}/series`, {
    verstrs, keys, max_points: maxPoints, x,
  });
}

/** Status fields (running? started when?) of just *verstrs*, by verstr. */
export async function fetchRunStatuses(
  ws: string, app: string, verstrs: string[],
): Promise<Record<string, Partial<RunStatus>>> {
  const p = new URLSearchParams({
    offset: "0", limit: String(verstrs.length), q: verstrInQuery(verstrs),
  });
  const body = await get<ExperimentRow[] | { rows: ExperimentRow[] }>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments?${p}`,
  );
  const rows = Array.isArray(body) ? body : body.rows;
  return Object.fromEntries(rows.map((r) => [r.verstr, r]));
}
