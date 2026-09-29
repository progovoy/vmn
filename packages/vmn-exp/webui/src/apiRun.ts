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

export interface LineageLink {
  input: string;
  artifact: string;
  digest: string | null;
  via: "uri" | "digest";
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
  models: LineageModel[];
  truncated: boolean;
}

/** The runs a run consumed from / fed, and the model versions registered from it. */
export function runLineage(ws: string, app: string, verstr: string, depth: number): Promise<Lineage> {
  return get<Lineage>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/` +
      `${encodeURIComponent(verstr)}/lineage?depth=${depth}`,
  );
}
