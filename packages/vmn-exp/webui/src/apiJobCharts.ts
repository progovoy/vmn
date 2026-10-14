/** The job Charts tab's reads (plan 23 §10, S2 `scope=`): the job's facets,
 *  chosen columns over every run of its subtree, and its top runs on a metric. */
import { api } from "./api";

/** Every run a chart may plot (the columns endpoint's cap). */
export const JOB_COLUMNS_LIMIT = 50_000;

/** The params and metrics of job *v*'s runs, with each param's value count. */
export const jobFacets = (ws: string, app: string, v: string) => api.facets(ws, app, { scope: v });

/** Columns *keys* over job *v*'s subtree, up to JOB_COLUMNS_LIMIT runs. */
export const jobColumns = (ws: string, app: string, v: string, keys: string[]) =>
  api.experimentsColumns(ws, app, keys, { scope: v, limit: JOB_COLUMNS_LIMIT });

/** The verstrs of job *v*'s best *k* runs on *metric* (its goal's direction). */
export const jobTopRuns = (ws: string, app: string, v: string, metric: string, k: number) =>
  api.experimentsPaged(ws, app, { scope: v, sort: metric, limit: k }).then(({ rows }) => rows.map((r) => r.verstr));
