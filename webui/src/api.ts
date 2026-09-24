import type {
  AppConfig, AppRow, Changelog, DiffResult, ExperimentColumns, ExperimentDetail,
  ExperimentFacets, ExperimentPage, ExperimentRow, Job, Meta, MetricsSchema, SnapshotRow, VersionRow,
  Workspace,
} from "./types";
import { appTag, BASE, get, post } from "./http";
import { PAGE_SIZE } from "./paging";

export { appTag };

export interface PageOpts {
  sort?: string;
  status?: string;
  query?: string;
  offset?: number;
  limit?: number;
  last?: number;
  /** Overrides the direction the metric's goal implies (``sort`` must be set). */
  order?: "asc" | "desc";
  /** Include archived runs (hidden by default). */
  archived?: boolean;
}

/** The leaderboard filter, as the list-shaped endpoints take it. */
function setFilter(p: URLSearchParams, opts: Omit<PageOpts, "offset" | "last">) {
  if (opts.sort) p.set("sort", opts.sort);
  if (opts.status) p.set("status", opts.status);
  if (opts.query) p.set("q", opts.query);
  if (opts.order) p.set("order", opts.order);
  if (opts.archived) p.set("archived", "1");
  if (opts.limit) p.set("limit", String(opts.limit));
}

/** One page of rows plus the server's total. Tolerates a server that still
 *  answers a plain list. */
async function fetchPage(
  ws: string, app: string, opts: PageOpts = {}
): Promise<{ rows: ExperimentRow[]; total: number }> {
  const p = new URLSearchParams({ offset: String(opts.offset ?? 0) });
  setFilter(p, { ...opts, limit: opts.limit ?? PAGE_SIZE });
  if (opts.last) p.set("last", String(opts.last));
  const body = await get<ExperimentRow[] | { rows: ExperimentRow[]; total: number }>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments?${p}`
  );
  return Array.isArray(body) ? { rows: body, total: body.length } : body;
}

/** Inverse of appTag: the real app name behind a URL tag. */
export const appName = (tag: string) => tag.replaceAll("-", "/");

/** Download URL of a run's artifact; nested names keep their `/`s, each
 *  component encoded on its own. */
export const artifactUrl = (ws: string, app: string, verstr: string, name: string) =>
  `${BASE}/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}` +
  `/artifacts/${name.split("/").map(encodeURIComponent).join("/")}`;

export const api = {
  meta: () => get<Meta>("/meta"),
  workspaces: () => get<Workspace[]>("/workspaces"),
  metricsSchema: (ws: string, app: string) =>
    get<MetricsSchema>(
      `/workspaces/${ws}/apps/${appTag(app)}/metrics-schema`
    ),
  /** App-wide filter vocabulary: every branch, metric and param key. */
  facets: (ws: string, app: string) =>
    get<ExperimentFacets>(`/workspaces/${ws}/apps/${appTag(app)}/experiments-facets`),
  addWorkspace: (name: string, opts: { remote?: string; path?: string }) =>
    post<Workspace>("/workspaces", { name, ...opts }),
  apps: (ws: string) => get<AppRow[]>(`/workspaces/${ws}/apps`),
  config: (ws: string, app: string, v?: string) =>
    get<AppConfig>(
      `/workspaces/${ws}/apps/${appTag(app)}/config${v ? `?v=${encodeURIComponent(v)}` : ""}`
    ),
  /** The first page of the leaderboard — bounded, never the whole app. */
  experiments: (
    ws: string, app: string, sort?: string, status?: string, query?: string
  ) =>
    fetchPage(ws, app, { sort, status, query, offset: 0, limit: PAGE_SIZE })
      .then(({ rows, total }) => Object.assign(rows, { total }) as ExperimentPage),
  experimentsPaged: (ws: string, app: string, opts?: PageOpts) =>
    fetchPage(ws, app, opts),
  /** Chosen columns (`metrics.loss`, `params.lr`, ...) over the whole
   *  filtered set, aligned with its verstrs. */
  experimentsColumns: (
    ws: string, app: string, keys: string[], opts: Omit<PageOpts, "offset" | "last"> = {},
  ) => {
    const p = new URLSearchParams({ keys: keys.join(",") });
    setFilter(p, opts);
    return get<ExperimentColumns>(`/workspaces/${ws}/apps/${appTag(app)}/experiments-columns?${p}`);
  },
  /** The newest *n* runs, newest first: `last` picks them by storage order on
   *  the server, whatever the leaderboard's sort. */
  recentExperiments: (ws: string, app: string, n = 20) =>
    fetchPage(ws, app, { last: n, limit: n }).then(({ rows }) =>
      [...rows].sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""))
    ),
  /** *maxPoints* asks the server to thin each metric's series to that many points. */
  experiment: (ws: string, app: string, verstr: string, maxPoints?: number) =>
    get<ExperimentDetail>(
      `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}` +
        (maxPoints ? `?max_points=${maxPoints}` : "")
    ),
  experimentsDiff: (ws: string, app: string, v: string, to: string) =>
    get<DiffResult>(
      `/workspaces/${ws}/apps/${appTag(app)}/experiments-diff` +
        `?v=${encodeURIComponent(v)}&to=${encodeURIComponent(to)}`
    ),
  versions: (ws: string, app: string) =>
    get<VersionRow[]>(`/workspaces/${ws}/apps/${appTag(app)}/versions`),
  action: (ws: string, app: string, action: string, body: Record<string, unknown>) =>
    post<Job>(`/workspaces/${ws}/apps/${appTag(app)}/actions/${action}`, body),
  job: (id: string) => get<Job>(`/jobs/${id}`),
  changelog: (ws: string, app: string, v: string, from?: string) =>
    get<Changelog>(
      `/workspaces/${ws}/apps/${appTag(app)}/changelog?v=${encodeURIComponent(v)}` +
        (from ? `&from=${encodeURIComponent(from)}` : "")
    ),
  snapshots: (ws: string, app: string) =>
    get<SnapshotRow[]>(`/workspaces/${ws}/apps/${appTag(app)}/snapshots`),
};
