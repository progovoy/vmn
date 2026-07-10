export interface Workspace {
  name: string;
  kind: string;
  path?: string;
  bucket?: string;
}

export interface AppRow {
  name: string;
  experiments: number;
}

export interface ExperimentRow {
  verstr: string;
  code_verstr: string;
  timestamp: string | null;
  note: string | null;
  branch: string | null;
  base_version: string | null;
  user_meta: Record<string, unknown> | null;
  metrics: Record<string, number | string>;
}

export interface SeriesPoint {
  step: number | null;
  ts: string | null;
  value: number;
}

export interface LogEntry {
  timestamp: string;
  type: string;
  [key: string]: unknown;
}

export interface ExperimentDetail {
  metadata: Record<string, unknown> & { verstr: string };
  log: LogEntry[];
  metrics: Record<string, number | string>;
  series: Record<string, SeriesPoint[]>;
  patches: Record<string, boolean>;
}

export interface VersionRow {
  tag: string;
  verstr: string;
  kind: string;
  release_mode?: string | null;
  prerelease?: string | null;
  previous_version?: string | null;
  branch?: string | null;
  commit?: string | null;
  timestamp?: number | null;
  services?: Record<string, string>;
  changesets?: Record<string, { hash?: string | null } | null>;
}

export interface DiffResult {
  from_verstr: string;
  to_verstr: string;
  metrics_delta: Record<string, { from: number | null; to: number | null }>;
  diff: string;
}

export interface SnapshotRow {
  verstr: string;
  timestamp: string | null;
  note: string | null;
  branch: string | null;
  base_version: string | null;
}
