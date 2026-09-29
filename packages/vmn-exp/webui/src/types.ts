export interface Workspace {
  name: string;
  kind: string;
  path?: string;
  store?: string;
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
  /** Which value the run ranks on; defaults from `goal` (else `last`). */
  summary?: "min" | "max" | "last";
  primary?: boolean;
}

/** A metric logged more than once: its last value and finite min/max
 *  (`null` when it never had a finite value). */
export interface MetricSummary {
  last: number | null;
  min: number | null;
  max: number | null;
}

export type MetricsSchema = Record<string, MetricSpec>;

export interface Meta {
  version: string;
  /** True when the server was started with --read-only; mutations return 403. */
  read_only?: boolean;
}

export interface Job {
  id: string;
  command: string[];
  status: string;
  exit_code: number | null;
  log: string;
}

/** Lifecycle of a `vmn-exp run` — "stuck" means the heartbeat went stale
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
  /** Direct inner runs per own status. */
  child_counts?: Record<string, number>;
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
  /** 1-based storage-order index — what `vmn-exp show <app> -v @N` resolves. */
  idx: number;
  verstr: string;
  code_verstr: string;
  timestamp: string | null;
  note: string | null;
  branch: string | null;
  base_version: string | null;
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

/** One param's row of `/experiments-importance`: its share of a random
 *  forest's impurity decrease for the target metric (the column sums to 1),
 *  its Pearson/Spearman correlation (null for categorical params) and the
 *  runs carrying both. */
export interface ParamImportanceEntry {
  param: string;
  importance: number;
  correlation: number | null;
  spearman: number | null;
  kind: "numeric" | "bool" | "categorical";
  n: number;
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
  /** The x metric's value at this point's step, when the series was joined
   *  on another metric (`x=` on the series endpoints). */
  x?: number;
}

export interface LogEntry {
  timestamp: string;
  type: string;
  _writer?: string;
  [key: string]: unknown;
}

/** Python/platform/packages information captured at run creation. */
export interface EnvData {
  /** Python version string or object. */
  python?: string | { version?: string; implementation?: string; executable?: string };
  /** Platform info: a string "System/Machine" or a struct. */
  platform?:
    | string
    | { system?: string; machine?: string; release?: string };
  /** Package name → version (only present when env.yml was small enough). */
  packages?: Record<string, string>;
  /** Key ML packages (always present in the summary). */
  key_packages?: Record<string, string>;
  packages_count?: number;
  packages_sha?: string;
  cuda?: Record<string, string>;
  hostname?: string;
  /** True when the file exceeded the size cap and packages is omitted. */
  truncated?: boolean;
  [key: string]: unknown;
}

/** A single dataset or artefact input logged via `run.log_input`. */
export interface InputEntry {
  uri: string;
  digest: string | null;
  kind?: string | null;
}

/** A file the run stored: an artifact, or a logged image/table. */
export interface OutputEntry {
  path: string;
  digest: string | null;
  size: number | null;
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
  /** Metrics that declare an x-axis metric (`define_metric` or conf.yml). */
  step_metrics?: Record<string, string>;
  /** Params as logged, verbatim — strings and booleans included. */
  params?: Record<string, unknown>;
  /** Each metric's summary value (best, per its policy — see MetricSpec). */
  metrics: Record<string, number | string | null>;
  /** last/min/max of every metric logged more than once. */
  metric_summary?: Record<string, MetricSummary>;
  series: Record<string, SeriesPoint[]>;
  patches: Record<string, boolean>;
  /** Names may be nested paths (`plots/loss.png`). */
  artifacts?: { name: string; size: number }[];
  status?: RunStatus;
  /** Python/platform/package environment captured at run creation. */
  env?: EnvData | null;
  /** Named inputs (datasets/artefacts) logged during the run. */
  inputs?: Record<string, InputEntry> | null;
  /** Files the run stored, by path (list rows never carry these). */
  outputs?: Record<string, OutputEntry> | null;
  /** Source identifier when the run was imported from an external system. */
  imported_from?: string | null;
  /** Logged images per key, one item per step (`run.log_image`). */
  media?: Record<string, MediaItem[]>;
  /** Logged tables per key, one item per step (`run.log_table`). */
  tables?: Record<string, TableItem[]>;
  /** Logged histograms per key; at most 100 evenly spaced steps each. */
  histograms?: Record<string, HistogramItem[]>;
  /** Steps logged per histogram key before thinning. */
  histograms_total?: Record<string, number>;
  /** The run (and step) this run was forked from; a fork is not a child. */
  forked_from?: ForkOrigin | null;
  /** Rewinds of this run, in log order: history past `step` was hidden. */
  rewinds?: RunRewind[];
}

export interface ForkOrigin {
  verstr: string;
  step: number | null;
}

export interface RunRewind {
  step: number;
  timestamp: string | null;
}

export interface MediaItem {
  step: number;
  /** Artifact path of the image (`media/<key>/<step>.png`). */
  path: string;
  caption?: string | null;
  width?: number | null;
  height?: number | null;
}

export interface TableItem {
  step: number;
  /** Artifact path of the columnar table document. */
  path: string;
  rows: number;
  columns: string[];
  total_rows?: number;
}

export interface HistogramItem {
  step: number;
  /** Bin edges: one more than `counts`. */
  bins: number[];
  counts: number[];
}

export interface TableColumn {
  name: string;
  type: "number" | "string" | "bool" | "null" | "mixed";
}

/** One page of a logged table from `/experiments/{v}/table/{path}`. */
export interface TablePage {
  columns: TableColumn[];
  rows: unknown[][];
  total: number;
  offset: number;
  truncated: boolean;
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
