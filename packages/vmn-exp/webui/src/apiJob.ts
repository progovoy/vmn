/** A job's endpoints (plan 23 §10, S3): its rollup summary, its failure
 *  clusters, and param importance scoped to its subtree. */
import { api } from "./api";
import { runBase } from "./apiRunCode";
import { get } from "./http";
import type { JobProgressFields, RunState } from "./types";

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

/** Per bucket: runs started, succeeded and failed in it, and released
 *  (handed back unfinished; only where some were). `t` is the bucket's
 *  start (epoch seconds or ISO). */
export interface TimelineBucket {
  t: number | string;
  started: number;
  succeeded: number;
  failed: number;
  released?: number;
}

export interface JobTimeline {
  bucket_sec: number;
  start: number | string | null;
  buckets: TimelineBucket[];
}

/** One value of a summary's split (plan 28 P3): its runs' counts and
 *  durations over the job's subtree; `other` (last) holds the values past
 *  the 12 listed. `key` is the group key (`∅` for no value), `clause` the
 *  query selecting the value's runs (null when the language can't say it). */
export interface JobSplitEntry
  extends Pick<JobProgressFields, "total" | "counts" | "done" | "never_started" | "lost" | "failed_pct"> {
  key: string | null;
  label: string;
  clause: string | null;
  other?: boolean;
  duration: JobDuration;
}

/** Finished runs' duration quantiles, seconds. */
export interface JobDuration {
  n: number;
  p50: number | null;
  p90: number | null;
}

/** A job page's summary (`experiments/{v}/summary`). */
export interface JobPageSummary extends JobProgressFields {
  verstr: string;
  name: string | null;
  idx: number | null;
  status: RunState;
  tree_status: RunState | null;
  kind: "outer" | "inner" | "single";
  sweep: boolean;
  started_at: string | null;
  finished_at: string | null;
  /** The main metric's name, when the server names it (else the first of `metrics`). */
  metric?: string | null;
  metrics: Record<string, JobMetric | null>;
  /** False when no tracked metric has a declared goal: `top` and `best` rank nothing. */
  ranked?: boolean;
  duration: JobDuration;
  failures: { sig: string; label: string; count: number }[];
  top: JobTopRun[];
  timeline: JobTimeline;
  /** The field `by` splits the subtree by (`?split=`, else the app's
   *  `experiment.ui.split_by`); null without one. */
  split?: string | null;
  by?: JobSplitEntry[] | null;
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

/** The rollup of job *v* (split by *split*, else the app's default); 404
 *  when *v* has no children. */
export const jobSummary = (ws: string, app: string, v: string, split?: string | null) =>
  get<JobPageSummary>(`${runBase(ws, app, v)}/summary${split ? `?${new URLSearchParams({ split })}` : ""}`);

export const FAILURES_LIMIT = 20;

export const jobFailures = (ws: string, app: string, v: string) =>
  get<JobFailures>(`${runBase(ws, app, v)}/failures?limit=${FAILURES_LIMIT}`);

/** Which params drive *metric* over job *v*'s subtree. */
export const jobImportance = (ws: string, app: string, v: string, metric: string) =>
  api.experimentsImportance(ws, app, metric, { scope: v });
