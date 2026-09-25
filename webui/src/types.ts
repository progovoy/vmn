export interface Workspace {
  name: string;
  kind: string;
  path?: string;
  bucket?: string;
}

export interface AppRow {
  name: string;
  experiments: number;
  versions: number;
}

export interface AppConfig {
  conf: Record<string, unknown>;
  text: string | null;
}

/** Per-metric leaderboard config from conf.yml (experiment.metrics). */
export interface MetricSpec {
  goal?: "min" | "max";
  primary?: boolean;
}

export type MetricsSchema = Record<string, MetricSpec>;

export interface Meta {
  version: string;
}

export interface Job {
  id: string;
  command: string[];
  status: string;
  exit_code: number | null;
  log: string;
  /** Ran fine but did nothing (e.g. snapshot create on a clean tree). */
  noop: boolean;
}

/** Lifecycle of a `vmn exp run` — "stuck" means the heartbeat went stale
 *  without an exit code, i.e. the runner died. */
export type RunState = "created" | "running" | "stuck" | "succeeded" | "failed";

/** Job status of a run, served both inline on list rows and as the detail
 *  response's `status` object. */
export interface RunStatus {
  status: RunState;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat: string | null;
  /** Elapsed while running, final duration once finished. */
  duration_sec: number | null;
  pid: number | null;
  host: string | null;
  command: string[] | null;
  /** Seconds since the last heartbeat. */
  stale_sec: number | null;
  /** How often the runner beats — the cadence status can change at. */
  heartbeat_interval_sec?: number | null;
  /** Verstr of the outer run that launched this one. */
  parent: string | null;
  children: string[];
  kind: "outer" | "inner" | "single";
  /** 0 for a top-level run. */
  depth: number;
  /** Rollup over this run and its whole subtree. */
  tree_status: string | null;
  last_metric_at: string | null;
  fleet?: Fleet | null;
}

export interface FleetChild {
  verstr: string;
  status: RunState;
  progress: number | null;
  progress_total: number | null;
}

export interface Fleet {
  expected: number;
  counts: Record<string, number>;
  children: FleetChild[];
}

/** Status fields are optional: older servers omit them entirely. */
export interface ExperimentRow extends Partial<RunStatus> {
  /** 1-based storage-order index — what `vmn exp show <app> -v @N` resolves. */
  idx: number;
  verstr: string;
  code_verstr: string;
  timestamp: string | null;
  note: string | null;
  branch: string | null;
  base_version: string | null;
  user_meta: Record<string, unknown> | null;
  /** Params as logged, verbatim — strings and booleans included. */
  params?: Record<string, unknown>;
  /** The numeric fold: metrics plus any param that parses as a number.
   *  `null` is a non-finite value (NaN/inf) the server could not send. */
  metrics: Record<string, number | string | null>;
  /** Human-readable run name; the verstr stands in when null/absent. */
  name?: string | null;
  tags?: Record<string, string>;
  archived?: boolean;
}

/** Chosen columns over a whole filtered set (`/experiments-columns`):
 *  `columns[key][i]` belongs to `verstrs[i]`. */
export interface ExperimentColumns {
  verstrs: string[];
  idx: number[];
  columns: Record<string, (number | string | boolean | null)[]>;
  total: number;
}

/** Every branch / metric key / param key across an app's runs. */
export interface ExperimentFacets {
  branches: string[];
  metric_keys: string[];
  param_keys: string[];
  total: number;
}

/** A page of leaderboard rows, with the server's count of every match. */
export type ExperimentPage = ExperimentRow[] & { total: number };

export interface SeriesPoint {
  step: number | null;
  ts: string | null;
  value: number;
}

export interface LogEntry {
  timestamp: string;
  type: string;
  _writer?: string;
  [key: string]: unknown;
}

export interface ExperimentDetail {
  metadata: Record<string, unknown> & { verstr: string };
  /** The newest log entries — the whole log only when requested with
   *  `include_log=1`, or from an older server that always sent all of it.
   *  Page older entries through `/log?offset&limit` instead. */
  log?: LogEntry[];
  /** The newest entries of the log (at most 200). */
  log_tail?: LogEntry[];
  /** How many entries the whole log holds. */
  log_total?: number;
  /** Points per metric before server-side downsampling. */
  series_total?: Record<string, number>;
  /** Params as logged, verbatim — strings and booleans included. */
  params?: Record<string, unknown>;
  metrics: Record<string, number | string | null>;
  series: Record<string, SeriesPoint[]>;
  patches: Record<string, boolean>;
  /** Names may be nested paths (`plots/loss.png`). */
  artifacts?: { name: string; size: number }[];
  status?: RunStatus;
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

export interface ChangelogEntry {
  type: string | null;
  scope: string | null;
  description: string;
  hash: string;
}

export interface ChangelogGroup {
  label: string;
  type: string | null;
  commits: ChangelogEntry[];
}

export interface ChangelogDep {
  path: string;
  name: string;
  from_commit: string;
  to_commit: string;
  breaking: ChangelogEntry[];
  groups: ChangelogGroup[];
}

export interface Changelog {
  to_verstr: string;
  from_verstr: string | null;
  to_commit: string | null;
  from_commit: string | null;
  breaking: ChangelogEntry[];
  groups: ChangelogGroup[];
  deps: ChangelogDep[];
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
