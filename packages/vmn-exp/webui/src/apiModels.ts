/**
 * Model registry API — JSON contract for the C9 backend to implement.
 *
 * Base URL pattern: /api/v1/workspaces/{ws}/models/...
 *
 * Endpoints
 * ---------
 * GET  /workspaces/{ws}/models[?kind=model|dataset]
 *   -> { models: ModelRow[] }
 *
 * GET  /workspaces/{ws}/models/{name}
 *   -> ModelDetail
 *
 * GET  /workspaces/{ws}/models/{name}/versions/{n}/lineage
 *   -> VersionLineage
 *
 * POST /workspaces/{ws}/models/{name}/versions
 *   body: RegisterVersionBody
 *   -> { version: number }      201 on creation
 *
 * POST /workspaces/{ws}/models/{name}/aliases
 *   body: MoveAliasBody
 *   -> {}                        409 if expect mismatches
 *
 * DELETE /workspaces/{ws}/models/{name}/aliases/{alias}
 *   -> {}
 *
 * POST /workspaces/{ws}/models/{name}/versions/{n}/status
 *   body: { status: "active" | "deprecated" | "deleted" }
 *   -> {}
 *
 * Mutations return 403 when the server is running in read-only mode.
 */
import { get, post, del } from "./http";
import type { LineageNode } from "./apiRun";

// ---------------------------------------------------------------------------
// JSON shapes
// ---------------------------------------------------------------------------

/** Models and datasets share the registry; absent = model (older servers). */
export type ModelKind = "model" | "dataset";

/** One row in the models table. */
export interface ModelRow {
  name: string;
  kind?: ModelKind;
  description: string | null;
  latest_version: number | null;
  /** Top-level alias → version number map. */
  aliases: Record<string, number>;
  versions_count: number;
  updated: string | null;
}

export interface ModelVersion {
  version: number;
  status: "active" | "deprecated" | "deleted";
  /** The experiment run this version was registered from. */
  run: { app: string; verstr: string };
  artifact_path: string | null;
  artifact_uri: string | null;
  aliases: string[];
  created: string | null;
  description: string | null;
}

export interface AuditEntry {
  ts: string;
  actor: string;
  type: "register" | "alias" | "status" | string;
  alias: string | null;
  version: number | null;
  status: string | null;
}

export interface ModelDetail {
  name: string;
  kind?: ModelKind;
  description: string | null;
  versions: ModelVersion[];
  aliases: Record<string, number>;
  audit: AuditEntry[];
}

/** Who made one version and which runs used it. */
export interface VersionLineage {
  model: string;
  version: number;
  kind: ModelKind;
  status: string;
  /** The run the version was registered from; null for a reference dataset. */
  producer: LineageNode | null;
  /** Runs recorded using it (`use_model`/`use_dataset`), first use first. */
  consumers: LineageNode[];
}

/** Body for registering a new model version. */
export interface RegisterVersionBody {
  run: { app: string; verstr: string };
  artifact_path?: string;
  alias?: string;
  description?: string;
}

/** Body for moving an alias to a different version. */
export interface MoveAliasBody {
  alias: string;
  version: number;
  /** Optimistic concurrency: fail if alias currently points to a different version. */
  expect?: number;
}

// ---------------------------------------------------------------------------
// Fetch functions
// ---------------------------------------------------------------------------

function modelsBase(ws: string) {
  return `/workspaces/${ws}/models`;
}

export const apiModels = {
  listModels: (ws: string, kind?: ModelKind) =>
    get<{ models: ModelRow[] }>(modelsBase(ws) + (kind ? `?kind=${kind}` : "")),

  getModel: (ws: string, name: string) =>
    get<ModelDetail>(`${modelsBase(ws)}/${encodeURIComponent(name)}`),

  versionLineage: (ws: string, name: string, version: number) =>
    get<VersionLineage>(
      `${modelsBase(ws)}/${encodeURIComponent(name)}/versions/${version}/lineage`,
    ),

  registerVersion: (ws: string, name: string, body: RegisterVersionBody) =>
    post<{ version: number }>(
      `${modelsBase(ws)}/${encodeURIComponent(name)}/versions`,
      body,
    ),

  moveAlias: (ws: string, name: string, alias: string, version: number, expect?: number) =>
    post<Record<string, never>>(
      `${modelsBase(ws)}/${encodeURIComponent(name)}/aliases`,
      { alias, version, expect },
    ),

  removeAlias: (ws: string, name: string, alias: string) =>
    del(`${modelsBase(ws)}/${encodeURIComponent(name)}/aliases/${encodeURIComponent(alias)}`),

  setVersionStatus: (
    ws: string, name: string, version: number,
    status: "active" | "deprecated" | "deleted",
  ) =>
    post<Record<string, never>>(
      `${modelsBase(ws)}/${encodeURIComponent(name)}/versions/${version}/status`,
      { status },
    ),
};
