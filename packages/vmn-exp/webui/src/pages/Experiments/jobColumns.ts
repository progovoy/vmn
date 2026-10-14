/** The Jobs view's columns (plan 23 W1, §3.1) and the sort keys of the
 *  contract (§10) their headers sort by. */
import type { CSSProperties } from "react";
import type { ExperimentRow, MetricsSchema } from "../../types";
import { metricGoal } from "../../util";
import type { Order } from "../../hooks/useLeaderboardView";
import { IDX_SORT } from "../LeaderboardHead";

export type { Order };

export interface JobColumn {
  id: string;
  label: string;
  width: number;
  /** The `sort=` key, none when not sortable. */
  sort?: string;
  /** What the header's sort says it does. */
  title?: string;
  numeric?: boolean;
}

export const JOB_SORTS = {
  progress: "job:progress", failed: "job:failed_pct", throughput: "job:throughput",
  best: "job:best", total: "job:total", started: "job:started",
} as const;

export const JOB_COLUMNS: readonly JobColumn[] = [
  { id: "check", label: "", width: 36 },
  { id: "idx", label: "#", width: 72, sort: IDX_SORT, title: "sort by run number (newest first)", numeric: true },
  { id: "status", label: "status", width: 124 },
  { id: "name", label: "job · progress", width: 380, sort: JOB_SORTS.progress, title: "sort by progress (furthest first)" },
  { id: "best", label: "best", width: 150, sort: JOB_SORTS.best, title: "sort by best (best first)", numeric: true },
  { id: "spread", label: "spread", width: 84 },
  { id: "runs", label: "runs", width: 76, sort: JOB_SORTS.total, title: "sort by runs (most first)", numeric: true },
  { id: "failed", label: "failed", width: 72, sort: JOB_SORTS.failed, title: "sort by failed share (most first)", numeric: true },
  { id: "throughput", label: "rate", width: 80, sort: JOB_SORTS.throughput, title: "sort by throughput (fastest first)", numeric: true },
  { id: "eta", label: "ETA", width: 132, numeric: true },
  { id: "branch", label: "branch", width: 120 },
  { id: "when", label: "started", width: 92, sort: JOB_SORTS.started, title: "sort by start (newest first)", numeric: true },
];

export const JOBS_WIDTH = JOB_COLUMNS.reduce((w, c) => w + c.width, 0);

/** Each column's width, one object per column for every row to share. */
export const COLUMN_STYLES: readonly CSSProperties[] = JOB_COLUMNS.map((c) => ({ width: c.width }));

/** Each column's body cell class. */
export const CELL_CLASSES: readonly string[] = JOB_COLUMNS.map((c) =>
  `jobs-cell-${c.id}${c.numeric ? " num" : ""}${c.id === "check" ? " check-cell" : ""}`);

/** The metric the Best and Spread columns are of: the jobs' rollup metric,
 *  else the schema's primary, else its first metric with a goal. */
export function mainMetric(rows: readonly ExperimentRow[], schema: MetricsSchema | null | undefined): string | null {
  const fromJob = rows.find((r) => r.job?.metric)?.job?.metric;
  if (fromJob) return fromJob;
  const entries = Object.entries(schema ?? {});
  return entries.find(([, s]) => s.primary)?.[0] ?? entries.find(([, s]) => s.goal)?.[0] ?? null;
}

/** The direction a header's first click sorts: best first for `job:best`
 *  (ascending for a metric that goes down), else the most first. */
export function bestOrder(sort: string, metric: string | null, schema: MetricsSchema | null | undefined): Order {
  if (sort === JOB_SORTS.best && metric && metricGoal(schema ?? null, metric) === "min") return "asc";
  return "desc";
}
