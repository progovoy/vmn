/** The job Charts tab's reads (plan 23 §10, S2 `scope=`): the job's facets,
 *  chosen columns over every run of its subtree, and its top runs on a metric. */
import { appTag, get } from "./http";
import type { ExperimentColumns, ExperimentFacets, ExperimentRow } from "./types";

/** Every run a chart may plot (the columns endpoint's cap). */
export const JOB_COLUMNS_LIMIT = 50_000;

const appPath = (ws: string, app: string) => `/workspaces/${ws}/apps/${appTag(app)}`;

/** The params and metrics of job *v*'s runs, with each param's value count. */
export const jobFacets = (ws: string, app: string, v: string) =>
  get<ExperimentFacets>(`${appPath(ws, app)}/experiments-facets?${new URLSearchParams({ scope: v })}`);

/** Columns *keys* over job *v*'s subtree, up to JOB_COLUMNS_LIMIT runs. */
export function jobColumns(ws: string, app: string, v: string, keys: string[]) {
  const p = new URLSearchParams({ scope: v, keys: keys.join(","), limit: String(JOB_COLUMNS_LIMIT) });
  return get<ExperimentColumns>(`${appPath(ws, app)}/experiments-columns?${p}`);
}

/** The verstrs of job *v*'s best *k* runs on *metric* (its goal's direction). */
export async function jobTopRuns(ws: string, app: string, v: string, metric: string, k: number) {
  const p = new URLSearchParams({ scope: v, sort: metric, offset: "0", limit: String(k) });
  const body = await get<ExperimentRow[] | { rows: ExperimentRow[] }>(`${appPath(ws, app)}/experiments?${p}`);
  return (Array.isArray(body) ? body : body.rows).map((r) => r.verstr);
}
