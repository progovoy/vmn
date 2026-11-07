/** The Jobs view's columns (plan 23 W1, §3.1) and the sort keys of the
 *  contract (§10) their headers sort by. */
import type { CSSProperties } from "react";
import type { Order } from "../../hooks/useLeaderboardView";
import { IDX_SORT } from "../LeaderboardHead";
import { UNKNOWN_BEST } from "../boardSortState";
import { goalOrder, type Goal } from "../../util";

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
  progress: "job:progress", failed: "job:failed_pct", rate: "job:rate", throughput: "job:throughput",
  value: "job:value", total: "job:total", started: "job:started", attention: "job:attention",
} as const;

export const JOB_COLUMNS: readonly JobColumn[] = [
  { id: "check", label: "", width: 36 },
  { id: "idx", label: "#", width: 72, sort: IDX_SORT, title: "sort by run number (newest first)", numeric: true },
  { id: "status", label: "status", width: 124, sort: JOB_SORTS.attention, title: "sort by needs attention (worst first)" },
  { id: "name", label: "outer run · progress", width: 440, sort: JOB_SORTS.progress, title: "sort by progress (furthest first)" },
  { id: "value", label: "value", width: 140, sort: JOB_SORTS.value, title: "sort by value (best first)", numeric: true },
  { id: "spread", label: "spread", width: 84 },
  { id: "runs", label: "runs", width: 76, sort: JOB_SORTS.total, title: "sort by runs (most first)", numeric: true },
  { id: "failed", label: "failed", width: 72, sort: JOB_SORTS.failed, title: "sort by failed share (most first)", numeric: true },
  { id: "rate", label: "rate", width: 92, sort: JOB_SORTS.rate, title: "sort by declared rate (fastest first)", numeric: true },
  { id: "throughput", label: "runs/min", width: 84, sort: JOB_SORTS.throughput, title: "sort by throughput, runs finished a minute (fastest first)", numeric: true },
  { id: "eta", label: "ETA", width: 132, numeric: true },
  { id: "branch", label: "branch", width: 120 },
  { id: "when", label: "started", width: 92, sort: JOB_SORTS.started, title: "sort by start (newest first)", numeric: true },
];

export const JOBS_WIDTH = JOB_COLUMNS.reduce((w, c) => w + c.width, 0);

/** Each column's width, one object per column for every row to share. */
export const COLUMN_STYLES: readonly CSSProperties[] = JOB_COLUMNS.map((c) => ({ width: c.width }));

/** The board's shared cell classes: the `#` cell is 12px mono, the width sized to it. */
const SHARED_CELL: Record<string, string> = { check: " check-cell", idx: " idx-cell" };

/** Each column's body cell class. */
export const CELL_CLASSES: readonly string[] = JOB_COLUMNS.map((c) =>
  `jobs-cell-${c.id}${c.numeric ? " num" : ""}${SHARED_CELL[c.id] ?? ""}`);

/** `job:value`'s best-first direction: toward its goal (the rows'
 *  `rolled.goal`), ascending without one (plan 32 F4), unknown while the
 *  goal is (undefined); null for every other column. */
export function jobValueOrder(sort: string, goal: Goal | undefined): Order | typeof UNKNOWN_BEST | null {
  if (sort !== JOB_SORTS.value) return null;
  return goal === undefined ? UNKNOWN_BEST : goalOrder(goal);
}
