/** Run-detail endpoints beyond the core `api` object: the paged run log and lineage. */
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

/** Models and datasets share the registry; absent = model (older servers). */
export type ModelKind = "model" | "dataset";

export interface LineageLink {
  input: string;
  artifact: string;
  digest: string | null;
  via: "uri" | "digest";
  /** Set when the artifact is a registered version's (e.g. via `use_model`). */
  model?: string;
  version?: number;
  kind?: ModelKind;
}

/** A reference dataset (`vmn-registry://` input) the run used. */
export interface LineageDataset {
  model: string;
  version: number;
  kind: ModelKind;
  input: string;
  digest: string | null;
  /** False once the version is deleted or gone; null when unknown. */
  found: boolean | null;
}

export interface LineageNode {
  app: string;
  verstr: string;
  name: string | null;
  timestamp: string | null;
  status: string | null;
  depth: number;
  found: boolean;
  links: LineageLink[];
}

export interface LineageModel {
  model: string;
  kind?: ModelKind;
  version: number;
  aliases: string[];
  status: string;
  artifact_path: string | null;
}

export interface Lineage {
  app: string;
  verstr: string;
  upstream: LineageNode[];
  downstream: LineageNode[];
  datasets?: LineageDataset[];
  models: LineageModel[];
  truncated: boolean;
}

/** The runs a run consumed from / fed, the reference datasets it used and
 *  the versions registered from it. */
export function runLineage(ws: string, app: string, verstr: string, depth: number): Promise<Lineage> {
  return get<Lineage>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/` +
      `${encodeURIComponent(verstr)}/lineage?depth=${depth}`,
  );
}

export interface MetricKeysQuery {
  prefix: string;
  offset: number;
  limit: number;
}

export interface MetricKeysPage {
  keys: { name: string; count: number }[];
  /** Names matching the prefix in all, across pages. */
  total: number;
  offset: number;
  limit: number | null;
}

/** One page of a run's metric names (name-ordered, prefix-filtered). */
export function metricKeys(
  ws: string, app: string, verstr: string, { prefix, offset, limit }: MetricKeysQuery,
): Promise<MetricKeysPage> {
  const qs = new URLSearchParams({ prefix, offset: String(offset), limit: String(limit) });
  return get<MetricKeysPage>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/` +
      `${encodeURIComponent(verstr)}/metric-keys?${qs}`,
  );
}
