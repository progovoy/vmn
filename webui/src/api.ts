import type {
  AppRow, DiffResult, ExperimentDetail, ExperimentRow, SnapshotRow,
  VersionRow, Workspace,
} from "./types";

const BASE = "/api/v1";

async function get<T>(path: string): Promise<T> {
  const token = sessionStorage.getItem("vmn_token");
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, { headers });
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

/** App names appear in URLs in vmn's dashed tag form (`/` -> `-`). */
export const appTag = (name: string) => name.replaceAll("/", "-");

export const api = {
  workspaces: () => get<Workspace[]>("/workspaces"),
  apps: (ws: string) => get<AppRow[]>(`/workspaces/${ws}/apps`),
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
  snapshots: (ws: string, app: string) =>
    get<SnapshotRow[]>(`/workspaces/${ws}/apps/${appTag(app)}/snapshots`),
};
