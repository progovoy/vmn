import type {
  AppConfig, AppRow, Changelog, DiffResult, ExperimentDetail, ExperimentRow,
  Job, SnapshotRow, VersionRow, Workspace,
} from "./types";

const BASE = "/api/v1";

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = sessionStorage.getItem("vmn_token");
  const headers: Record<string, string> = { ...extra };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
  if (res.status === 401) {
    const entered = window.prompt("vmn ui token:");
    if (entered) {
      sessionStorage.setItem("vmn_token", entered);
      return get<T>(path);
    }
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(b.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/** App names appear in URLs in vmn's dashed tag form (`/` -> `-`). */
export const appTag = (name: string) => name.replaceAll("/", "-");

export const api = {
  workspaces: () => get<Workspace[]>("/workspaces"),
  addWorkspace: (name: string, opts: { remote?: string; path?: string }) =>
    post<Workspace>("/workspaces", { name, ...opts }),
  apps: (ws: string) => get<AppRow[]>(`/workspaces/${ws}/apps`),
  config: (ws: string, app: string) =>
    get<AppConfig>(`/workspaces/${ws}/apps/${appTag(app)}/config`),
  experiments: (ws: string, app: string, sort?: string) =>
    get<ExperimentRow[]>(
      `/workspaces/${ws}/apps/${appTag(app)}/experiments` +
        (sort ? `?sort=${encodeURIComponent(sort)}` : "")
    ),
  experiment: (ws: string, app: string, verstr: string) =>
    get<ExperimentDetail>(
      `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}`
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
