/** A job's endpoints (plan 23 §10, S3): its rollup summary, its failure
 *  clusters, and param importance scoped to its subtree. */
import { appTag, get } from "./http";
import type { ParamImportanceEntry, RunState } from "./types";

/** A job's runs per state (the D12 states; `waiting` = created). */
export interface JobCounts {
  running: number;
  waiting: number;
  succeeded: number;
  failed: number;
  stuck: number;
}

export interface HistBin {
  lo: number;
  hi: number;
  count: number;
}

/** One tracked metric over the subtree; `best` follows the metric's goal. */
export interface JobMetric {
  n: number;
  min: number;
  max: number;
  mean: number;
  best: number;
  best_verstr: string;
  hist: HistBin[];
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
}

export interface JobTopRun {
  verstr: string;
  idx: number | null;
  name: string | null;
  status: RunState;
  value: number | null;
}

/** Per bucket: runs started, succeeded and failed in it. `t` is the bucket's
 *  start (epoch seconds or ISO). */
export interface TimelineBucket {
  t: number | string;
  started: number;
  succeeded: number;
  failed: number;
}

export interface JobTimeline {
  bucket_sec: number;
  start: number | string | null;
  buckets: TimelineBucket[];
}

export interface JobSummary {
  verstr: string;
  name: string | null;
  idx: number | null;
  status: RunState;
  tree_status: RunState | null;
  kind: "outer" | "inner" | "single";
  sweep: boolean;
  total: number;
  counts: JobCounts;
  done: number;
  expected: number;
  progress: number | null;
  failed_pct: number;
  throughput_per_min: number;
  eta_sec: number | null;
  started_at: string | null;
  finished_at: string | null;
  /** The main metric's name, when the server names it (else the first of `metrics`). */
  metric?: string | null;
  metrics: Record<string, JobMetric | null>;
  duration: { n: number; p50: number | null; p90: number | null };
  failures: { sig: string; label: string; count: number }[];
  top: JobTopRun[];
  timeline: JobTimeline;
}

export interface FailureCluster {
  sig: string;
  label: string;
  count: number;
  /** Of the job's failures, 0..1. */
  share: number;
  first_at: string | null;
  last_at: string | null;
  hosts: { host: string; count: number }[];
  /** Params overrepresented in the cluster: `share` in it vs `base_share` in the job. */
  params: { key: string; value: unknown; share: number; base_share: number }[];
  example_verstr: string | null;
}

export interface JobFailures {
  total_failed: number;
  clusters: FailureCluster[];
}

const runPath = (ws: string, app: string, v: string) =>
  `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(v)}`;

/** The rollup of job *v*; 404 when *v* has no children. */
export const jobSummary = (ws: string, app: string, v: string) =>
  get<JobSummary>(`${runPath(ws, app, v)}/summary`);

export const FAILURES_LIMIT = 20;

export const jobFailures = (ws: string, app: string, v: string) =>
  get<JobFailures>(`${runPath(ws, app, v)}/failures?limit=${FAILURES_LIMIT}`);

/** Which params drive *metric* over job *v*'s subtree. */
export function jobImportance(ws: string, app: string, v: string, metric: string) {
  const p = new URLSearchParams({ metric, scope: v });
  return get<ParamImportanceEntry[]>(`/workspaces/${ws}/apps/${appTag(app)}/experiments-importance?${p}`);
}
